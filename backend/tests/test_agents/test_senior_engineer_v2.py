"""D11 Checkpoint 4 — senior_engineer agent unit tests.

Pins the agent's contract across:
  • Pass 3b §7.1 failure classes (A: malformed input, C: specialist
    error, E: revoked-mid-request / memory unavailable)
  • Three-mode schema validation (pr_review / chat_help / rubric_score)
  • Memory read/write integration
  • SeniorEngineerInput's resolved_code() field-resolution shim
  • Phantom-claim contract: stub LLM emits an "I ran" line; verify the
    no-execution-claim regex (CP3) catches it as a regression check

Failure classes B (invalid agent target) and D (cost exhausted) are
dispatch-layer concerns covered in test_checkpoint3_dispatch.py;
this file's coverage is the per-agent half of those classes (i.e.
"the agent doesn't crash if invoked under that condition"), exercised
implicitly via the schema-validation tests below.

Test pattern matches test_billing_support.py — construct a fresh
SeniorEngineerAgent with a stubbed LLM, drive run() directly with a
MagicMock'd AgentContext, patch tool_call + memory accessors so we
exercise only the agent-class behavior under the failure mode
in question.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext
from app.agents.primitives.communication import CallChain
from app.agents.primitives.tools import ToolCallResult
from app.agents.senior_engineer_v2 import (
    SeniorEngineerAgent,
    SeniorEngineerInput,
)
from app.agents.tools.agent_specific.senior_engineer.lookup_prior_reviews import (
    LookupPriorReviewsOutput,
)
from app.agents.tools.agent_specific.senior_engineer.lookup_prior_submissions import (
    LookupPriorSubmissionsOutput,
)
from app.schemas.agents.senior_engineer import SeniorEngineerOutput


# ── Stub LLMs ──────────────────────────────────────────────────────


class _ValidPrReviewLLM:
    """Returns a valid pr_review-shaped JSON. Mirrors what real
    MiniMax responses produce for a structured code review."""

    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "mode": "pr_review",
                "verdict": "request_changes",
                "headline": "Bare except hides real bugs",
                "strengths": ["Clear function name"],
                "comments": [
                    {
                        "line": 12,
                        "severity": "blocking",
                        "message": "Bare `except:` here catches KeyboardInterrupt. Narrow it.",
                        "suggested_change": "except (ValueError, KeyError):",
                    }
                ],
                "next_step": "Narrow the except and resubmit.",
                "patterns_observed": ["bare-except"],
                "handoff_request": None,
            }
        )
        msg.usage_metadata = {"input_tokens": 200, "output_tokens": 150}
        msg.response_metadata = {"model": "MiniMax-M2.7"}
        return msg


class _ValidChatHelpLLM:
    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "mode": "chat_help",
                "explanation": (
                    "If you run this with n=5, range(n) iterates "
                    "0..4 — it would stop before 5."
                ),
                "code_suggestion": "for i in range(n + 1):\n    ...",
                "patterns_observed": [],
                "handoff_request": None,
            }
        )
        msg.usage_metadata = {"input_tokens": 80, "output_tokens": 60}
        msg.response_metadata = {"model": "MiniMax-M2.7"}
        return msg


class _ValidRubricScoreLLM:
    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "mode": "rubric_score",
                "score": 82,
                "dimension_scores": {
                    "correctness": 18,
                    "readability": 16,
                    "idiomatic": 14,
                },
                "rubric_feedback": "Strong correctness; idioms looser.",
                "patterns_observed": [],
                "handoff_request": None,
            }
        )
        msg.usage_metadata = {"input_tokens": 120, "output_tokens": 90}
        msg.response_metadata = {"model": "MiniMax-M2.7"}
        return msg


class _MalformedJsonLLM:
    """Returns prose that doesn't contain a JSON object — Pass 3b §7.1
    Class A (malformed LLM output)."""

    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = "Sorry, I can't help with that."
        msg.usage_metadata = {"input_tokens": 50, "output_tokens": 10}
        msg.response_metadata = {"model": "MiniMax-M2.7"}
        return msg


class _RaisingLLM:
    """Raises during ainvoke — Pass 3b §7.1 Class C (specialist error)."""

    async def ainvoke(self, messages: Any) -> Any:
        raise RuntimeError("simulated upstream LLM outage")


class _PhantomExecutionClaimLLM:
    """Returns a chat_help payload whose explanation includes an
    execution-claim phrase. The CP3 regex catches it; this test
    pins that the phrase reaches the response (the agent does NOT
    silently strip such claims — surfacing them is the correct
    failure mode so the regex test fires)."""

    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "mode": "chat_help",
                "explanation": (
                    "I ran this and the test passed on my machine. "
                    "Looks good!"
                ),
                "patterns_observed": [],
                "handoff_request": None,
            }
        )
        msg.usage_metadata = {"input_tokens": 30, "output_tokens": 40}
        msg.response_metadata = {"model": "MiniMax-M2.7"}
        return msg


# ── Common helpers ─────────────────────────────────────────────────


def _make_agent(llm: Any) -> SeniorEngineerAgent:
    """Construct a fresh agent with a stub LLM. Avoids the agentic
    registry entirely (other tests clear it between runs)."""
    agent = SeniorEngineerAgent()
    agent._build_llm = lambda *a, **kw: llm  # type: ignore[method-assign]
    return agent


def _make_ctx(student_id: uuid.UUID | None = None) -> AgentContext:
    chain = CallChain.start_root(
        caller="test_senior_engineer_v2",
        user_id=student_id,
    )
    session = MagicMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    return AgentContext(
        user_id=student_id,
        chain=chain,
        session=session,
        permissions=frozenset(),
        extra={"_llm_usage": []},
    )


def _stub_lookup_tools(tool_name: str) -> ToolCallResult:
    """Return empty-shape outputs for the two senior_engineer lookups
    + a no-op log_event ack. Used as a default tool_call side_effect."""
    if tool_name == "lookup_prior_reviews":
        return ToolCallResult(
            tool_name=tool_name,
            output=LookupPriorReviewsOutput(reviews=[], total_returned=0),
            status="ok",
        )
    if tool_name == "lookup_prior_submissions":
        return ToolCallResult(
            tool_name=tool_name,
            output=LookupPriorSubmissionsOutput(
                submissions=[], total_returned=0
            ),
            status="ok",
        )
    if tool_name == "log_event":
        from app.agents.tools.universal.log_event import LogEventOutput

        return ToolCallResult(
            tool_name=tool_name,
            output=LogEventOutput(logged=True),
            status="ok",
        )
    raise AssertionError(f"unexpected tool_call: {tool_name}")


async def _stub_tool_call_default(
    tool_name: str, args: Any, ctx_arg: Any
) -> ToolCallResult:
    return _stub_lookup_tools(tool_name)


# ── Failure-class tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_class_a_malformed_llm_output_falls_back_gracefully() -> None:
    """Pass 3b §7.1 Class A — malformed LLM output.

    LLM returns prose with no JSON object. The agent's _call_llm
    catches the parse failure and emits a chat_help-shaped fallback
    pointing the student at support. Never raises to dispatch.
    """
    student_id = uuid.uuid4()
    agent = _make_agent(_MalformedJsonLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(
            SeniorEngineerInput(code="def f(): pass"),
            ctx,
        )

    # Fallback must be schema-valid + readable + point at support.
    assert result["mode"] == "chat_help"
    assert "support@aicareeros.com" in result["explanation"]
    SeniorEngineerOutput.model_validate(
        {k: v for k, v in result.items() if k != "answer"}
    )


@pytest.mark.asyncio
async def test_class_c_llm_raises_falls_back_gracefully() -> None:
    """Pass 3b §7.1 Class C — specialist call failure.

    LLM raises during ainvoke (network outage, rate limit, etc.).
    Same fallback path as Class A — the agent never raises.
    """
    student_id = uuid.uuid4()
    agent = _make_agent(_RaisingLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(
            SeniorEngineerInput(code="def f(): pass"),
            ctx,
        )

    assert result["mode"] == "chat_help"
    assert "support@aicareeros.com" in result["explanation"]


@pytest.mark.asyncio
async def test_class_e_memory_write_failure_does_not_break_response() -> None:
    """Pass 3b §7.1 Class E — memory/storage unavailable mid-request.

    The agent's response must still ship even when the post-LLM
    memory write throws. asyncpg-rollback discipline on the
    _record_interaction wrapper catches the error, rolls back the
    session, logs, and returns the answer to the student.
    """
    student_id = uuid.uuid4()
    agent = _make_agent(_ValidPrReviewLLM())
    ctx = _make_ctx(student_id=student_id)

    async def _failing_record_interaction(**_kwargs: Any) -> None:
        raise RuntimeError("simulated agent_memory write failure")

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(
            agent,
            "_record_interaction",
            side_effect=_failing_record_interaction,
        ),
    ):
        result = await agent.run(
            SeniorEngineerInput(code="def f(): pass", problem_context="ctx"),
            ctx,
        )

    # Response shipped — verdict + headline came through despite
    # the memory write blowing up.
    assert result["mode"] == "pr_review"
    assert result["verdict"] == "request_changes"
    # asyncpg-rollback discipline ran — verify session.rollback was
    # awaited.
    ctx.session.rollback.assert_awaited()


# ── Three-mode schema validation through the agent ─────────────────


@pytest.mark.asyncio
async def test_pr_review_mode_emits_valid_output() -> None:
    student_id = uuid.uuid4()
    agent = _make_agent(_ValidPrReviewLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(
            SeniorEngineerInput(
                code="def f(): pass",
                problem_context="exercise statement",
            ),
            ctx,
        )

    assert result["mode"] == "pr_review"
    assert result["verdict"] == "request_changes"
    assert result["comments"][0]["severity"] == "blocking"
    # Synthesized answer field for dispatch _extract_text projection.
    assert "Bare except" in result["answer"]
    assert result["handoff_request"] is None  # Option B
    SeniorEngineerOutput.model_validate(
        {k: v for k, v in result.items() if k != "answer"}
    )


@pytest.mark.asyncio
async def test_chat_help_mode_emits_valid_output() -> None:
    student_id = uuid.uuid4()
    agent = _make_agent(_ValidChatHelpLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(
            SeniorEngineerInput(code="for i in range(n): pass"),
            ctx,
        )

    assert result["mode"] == "chat_help"
    assert result["explanation"] is not None
    assert result["code_suggestion"] == "for i in range(n + 1):\n    ..."
    # Mode inference happened (no problem_context, no rubric).
    SeniorEngineerOutput.model_validate(
        {k: v for k, v in result.items() if k != "answer"}
    )


@pytest.mark.asyncio
async def test_rubric_score_mode_emits_valid_output() -> None:
    student_id = uuid.uuid4()
    agent = _make_agent(_ValidRubricScoreLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(
            SeniorEngineerInput(
                code="def f(): pass",
                rubric="dimensions: correctness, readability, idiomatic",
            ),
            ctx,
        )

    assert result["mode"] == "rubric_score"
    assert result["score"] == 82
    assert result["dimension_scores"]["correctness"] == 18
    SeniorEngineerOutput.model_validate(
        {k: v for k, v in result.items() if k != "answer"}
    )


# ── Mode inference ─────────────────────────────────────────────────


def test_mode_resolution_caller_supplied_wins() -> None:
    out, was_inferred = SeniorEngineerAgent._resolve_mode(
        SeniorEngineerInput(code="x", mode="rubric_score")
    )
    assert out == "rubric_score"
    assert was_inferred is False


def test_mode_resolution_inferred_pr_review_when_problem_context() -> None:
    out, was_inferred = SeniorEngineerAgent._resolve_mode(
        SeniorEngineerInput(code="x", problem_context="ctx")
    )
    assert out == "pr_review"
    assert was_inferred is True


def test_mode_resolution_inferred_rubric_when_rubric_supplied() -> None:
    out, was_inferred = SeniorEngineerAgent._resolve_mode(
        SeniorEngineerInput(code="x", rubric="dim: c, r")
    )
    assert out == "rubric_score"
    assert was_inferred is True


def test_mode_resolution_default_chat_help() -> None:
    out, was_inferred = SeniorEngineerAgent._resolve_mode(
        SeniorEngineerInput(code="x")
    )
    assert out == "chat_help"
    assert was_inferred is True


def test_mode_resolution_invalid_caller_mode_falls_through_to_inference() -> (
    None
):
    """A caller-supplied mode that isn't in the valid set is ignored;
    the agent infers from input shape instead. Defends against
    typoed mode strings reaching the LLM as junk hints."""
    out, was_inferred = SeniorEngineerAgent._resolve_mode(
        SeniorEngineerInput(code="x", mode="freeform_taste_review"),
    )
    assert out == "chat_help"
    assert was_inferred is True


# ── resolved_code() field-resolution ───────────────────────────────


def test_resolved_code_prefers_code_field() -> None:
    inp = SeniorEngineerInput(
        code="prefer", question="ignore", task="ignore"
    )
    assert inp.resolved_code() == "prefer"


def test_resolved_code_falls_back_to_question() -> None:
    inp = SeniorEngineerInput(question="from-supervisor")
    assert inp.resolved_code() == "from-supervisor"


def test_resolved_code_falls_back_to_task() -> None:
    inp = SeniorEngineerInput(task="from-chain-step")
    assert inp.resolved_code() == "from-chain-step"


def test_resolved_code_falls_back_to_user_message() -> None:
    inp = SeniorEngineerInput(user_message="raw user text")
    assert inp.resolved_code() == "raw user text"


def test_resolved_code_returns_none_when_all_empty() -> None:
    inp = SeniorEngineerInput()
    assert inp.resolved_code() is None


def test_resolved_code_treats_whitespace_as_empty() -> None:
    inp = SeniorEngineerInput(code="   ", question="\t\n")
    assert inp.resolved_code() is None


@pytest.mark.asyncio
async def test_run_with_no_input_text_returns_fail_honest_chat_help() -> None:
    """When all four input-text fields are empty, the agent returns
    a chat_help-shaped fallback asking the student to re-share.
    Never raises to dispatch (which would surface as 500)."""
    student_id = uuid.uuid4()
    agent = _make_agent(_ValidChatHelpLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(SeniorEngineerInput(), ctx)

    assert result["mode"] == "chat_help"
    assert "didn't see any code or question" in result["explanation"]


# ── Defense-in-depth: drop phantom handoff_request ─────────────────


class _PhantomHandoffLLM:
    """Returns a payload that violates the prompt's handoff_request
    instruction by populating a non-null handoff_request. The agent's
    run() should defensively drop it (Option B contract)."""

    async def ainvoke(self, messages: Any) -> Any:
        msg = MagicMock()
        msg.content = json.dumps(
            {
                "mode": "chat_help",
                "explanation": "Some explanation.",
                "patterns_observed": [],
                "handoff_request": {
                    "target_agent": "learning_coach",
                    "reason": "ignored under Option B",
                    "suggested_context": {},
                    "handoff_type": "suggested",
                },
            }
        )
        msg.usage_metadata = {"input_tokens": 30, "output_tokens": 30}
        msg.response_metadata = {"model": "MiniMax-M2.7"}
        return msg


@pytest.mark.asyncio
async def test_phantom_handoff_request_dropped_per_option_b() -> None:
    """The deployed prompt instructs the LLM to keep handoff_request
    null in v1 (Option B). If the LLM ignores that, run() drops it.
    Pin: handoff_request is None on the response no matter what the
    LLM emitted."""
    student_id = uuid.uuid4()
    agent = _make_agent(_PhantomHandoffLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(
            SeniorEngineerInput(code="def f(): pass"),
            ctx,
        )

    assert result["handoff_request"] is None, (
        "Option B contract violated — phantom handoff_request leaked "
        "through to the response"
    )


# ── Phantom-execution-claim regression ─────────────────────────────


_VIOLATION_PHRASES = re.compile(
    r"\b(I ran|I executed|the test passed|the test failed|"
    r"when I executed|the output is)\b",
    re.IGNORECASE,
)


@pytest.mark.asyncio
async def test_execution_claim_in_llm_output_reaches_response_for_regex_to_catch() -> (
    None
):
    """The agent does NOT silently strip execution-claim phrases the
    LLM emits — that would hide prompt regressions. Instead the
    response carries the phrases and CP3's no-execution-claim regex
    test surfaces them as a contract violation. Pin both:
      1. The phrase reaches the response (agent isn't masking).
      2. The regex would catch it at the test layer.

    This is the regression test for the phantom-claim contract under
    a stub LLM that violates the prompt's hard constraint."""
    student_id = uuid.uuid4()
    agent = _make_agent(_PhantomExecutionClaimLLM())
    ctx = _make_ctx(student_id=student_id)

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "_record_interaction", return_value=None),
    ):
        result = await agent.run(
            SeniorEngineerInput(code="def f(): pass"),
            ctx,
        )

    # 1. The phrase reaches the response (agent doesn't mask LLM
    #    contract violations).
    assert "I ran" in result["explanation"]
    assert "the test passed" in result["explanation"]

    # 2. CP3's regex would catch the violation in a real-LLM smoke.
    violations = _VIOLATION_PHRASES.findall(result["explanation"])
    assert violations, (
        "Phantom-execution-claim regression: the no-execution-claim "
        "regex must catch violations the LLM emits despite the prompt's "
        "hard constraint"
    )


# ── Memory R/W integration through the agent ──────────────────────


@pytest.mark.asyncio
async def test_record_interaction_writes_three_memory_shapes() -> None:
    """A successful pr_review with a populated patterns_observed
    list writes three memory shapes:
      • feedback:code_review:{date}
      • submission:code:{date}
      • senior_engineer:pattern:{slug} (one per pattern)
    """
    student_id = uuid.uuid4()
    agent = _make_agent(_ValidPrReviewLLM())
    ctx = _make_ctx(student_id=student_id)

    write_calls: list[Any] = []

    class _CapturingStore:
        async def write(self, memory_write: Any) -> Any:
            write_calls.append(memory_write)
            return MagicMock()

        async def recall(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

    with (
        patch.object(agent, "tool_call", side_effect=_stub_tool_call_default),
        patch.object(
            agent,
            "_recall_engineering_memories",
            return_value={"patterns": [], "related": []},
        ),
        patch.object(agent, "memory", return_value=_CapturingStore()),
    ):
        result = await agent.run(
            SeniorEngineerInput(
                code="def parse_payload(): pass",
                problem_context="exercise",
            ),
            ctx,
        )

    assert result["mode"] == "pr_review"
    keys = [m.key for m in write_calls]
    # At least one feedback row + one submission row + one pattern row
    assert any(k.startswith("feedback:code_review:") for k in keys)
    assert any(k.startswith("submission:code:") for k in keys)
    assert any(
        k.startswith("senior_engineer:pattern:bare-except") for k in keys
    )


@pytest.mark.asyncio
async def test_recall_engineering_memories_skips_when_no_user_id() -> None:
    """No student_id in the context → memory recall returns the
    empty shape rather than failing on a None user_id."""
    agent = _make_agent(_ValidChatHelpLLM())
    ctx = _make_ctx(student_id=None)

    out = await agent._recall_engineering_memories(
        resolved_code="def f(): pass", ctx=ctx
    )
    assert out == {"patterns": [], "related": []}


@pytest.mark.asyncio
async def test_gather_lookup_data_skips_when_no_user_id() -> None:
    """Same shape — no user_id → no tool calls, empty defaults."""
    agent = _make_agent(_ValidChatHelpLLM())
    ctx = _make_ctx(student_id=None)

    out = await agent._gather_lookup_data(
        resolved_code="def f(): pass", ctx=ctx
    )
    assert out == {"prior_reviews": [], "prior_submissions": []}


# ── _compose_answer_text ──────────────────────────────────────────


def test_compose_answer_text_chat_help_includes_code_suggestion() -> None:
    out = SeniorEngineerOutput(
        mode="chat_help",
        explanation="Use range(n+1) to include n.",
        code_suggestion="for i in range(n+1): ...",
    )
    text = SeniorEngineerAgent._compose_answer_text(out)
    assert "Use range(n+1) to include n." in text
    assert "for i in range(n+1): ..." in text


def test_compose_answer_text_pr_review_orders_sections() -> None:
    out = SeniorEngineerOutput(
        mode="pr_review",
        verdict="approve",
        headline="Looks good",
        strengths=["clear names", "type hints"],
        comments=[],
        next_step="Ship it.",
    )
    text = SeniorEngineerAgent._compose_answer_text(out)
    assert text.startswith("Looks good")
    assert "Verdict: approve" in text
    assert "Strengths" in text
    assert "Next step" in text


def test_compose_answer_text_rubric_score_includes_score() -> None:
    out = SeniorEngineerOutput(
        mode="rubric_score",
        score=78,
        dimension_scores={"correctness": 18},
        rubric_feedback="Strong correctness, looser idioms.",
    )
    text = SeniorEngineerAgent._compose_answer_text(out)
    assert "Score: 78/100" in text
    assert "Strong correctness" in text


def test_compose_answer_text_pr_review_empty_falls_back_to_review_complete() -> (
    None
):
    """An otherwise empty pr_review output falls back to a generic
    'Review complete.' string rather than emitting empty response
    text. Defensive: dispatch._extract_text reads the answer field
    so it must always be non-empty."""
    out = SeniorEngineerOutput(mode="pr_review")
    text = SeniorEngineerAgent._compose_answer_text(out)
    assert text == "Review complete."
