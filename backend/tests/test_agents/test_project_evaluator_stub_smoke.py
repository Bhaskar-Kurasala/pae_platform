"""D14c CP2 — stub-LLM smoke tests for project_evaluator_v2.

Drives ProjectEvaluatorAgent.run() end-to-end with:
  • a stub LLM that returns a hardcoded ProjectEvaluatorOutput JSON
  • stubbed tool registry entries for the 4 reads
    (read_capstone_submission_content, read_rubric_for_capstone,
    read_student_full_progress, read_capstone_status)

Verifies:
  • Happy path with rubric: 4 tools fire IN ORDER before LLM, schema
    validates
  • D-4 early exit on non-capstone: rubric/progress/capstone-status
    tools NOT called; LLM receives NON_CAPSTONE_SUBMISSION marker;
    output is refusal shape
  • D-4 early exit on submission-not-found: same routing as
    non-capstone (architectural-contract-violation symmetry)
  • D-E rubric unavailable: LLM receives RUBRIC_UNAVAILABLE marker;
    output forced to refusal shape (rubric_available=False,
    dimension_scores=[], handoff_request=None)
  • Runtime backstop: rubric_available=True with empty
    dimension_scores → forced to False (D-E enforcement gap defense)
  • shape-drift defenses: extra top-level field stripped;
    narrative_feedback overshoot truncated
  • Bug 21 regression: handoff_request.suggested_context dict OK;
    string rejected at schema level
  • Pattern 16: ensure_tools_loaded() called at module level
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.primitives.communication import _active_session
from app.agents.primitives.tools import ensure_tools_loaded, registry
from app.agents.project_evaluator import (
    NON_CAPSTONE_SUBMISSION_MARKER,
    RUBRIC_UNAVAILABLE_MARKER,
    ProjectEvaluatorAgent,
)
from app.schemas.agents.project_evaluator import ProjectEvaluatorInput

# Pattern 16: tool registry must be populated for stub-smoke.
ensure_tools_loaded()


# ── Test doubles ───────────────────────────────────────────────────


class _StubResponse:
    """LangChain ainvoke()-shape response with dict-style content blocks
    (MiniMax Anthropic-compatible endpoint shape — exercises Bug 10a)."""

    def __init__(self, json_text: str) -> None:
        self.content = [
            {"type": "thinking", "thinking": "internal reasoning skipped"},
            {"type": "text", "text": json_text},
        ]
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 50}


class _StubLLM:
    def __init__(self, json_text: str) -> None:
        self._json_text = json_text
        self.calls: list[Any] = []

    async def ainvoke(self, messages: Any, **_: Any) -> _StubResponse:
        self.calls.append(messages)
        return _StubResponse(self._json_text)

    def last_user_block(self) -> str:
        """Return the user-message text from the most recent call —
        the prompt's `## Capstone gate` / `## Rubric` markers live here."""
        if not self.calls:
            return ""
        for msg in self.calls[-1]:
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def stub_session() -> Any:
    return MagicMock(spec=AsyncSession)


@pytest.fixture
def stub_ctx(stub_session: Any) -> AgentContext:
    return AgentContext(
        user_id=uuid.uuid4(),
        chain=CallChain.start_root(caller="test"),
        session=stub_session,
        extra={"_llm_usage": []},
    )


@pytest.fixture
def patch_active_session(stub_session: Any):
    token = _active_session.set(stub_session)
    yield
    _active_session.reset(token)


@pytest.fixture
def patch_llm(monkeypatch: pytest.MonkeyPatch):
    def _install(json_text: str) -> _StubLLM:
        stub = _StubLLM(json_text)
        monkeypatch.setattr(
            "app.agents.llm_factory.build_llm",
            lambda **_kw: stub,
        )
        return stub

    return _install


@pytest.fixture
def patch_executor_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch out audit-row writes that need Postgres."""
    async def _noop(*_args: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(
        "app.agents.primitives.tools.ToolExecutor._record_tool_call",
        _noop,
        raising=False,
    )


@pytest.fixture
def patch_tools(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the four read tools' funcs with capture-stubs.

    Returns a dict the test populates with per-tool return values
    BEFORE invoking the agent. Each tool also records its call args
    so tests can assert ordering and arguments.
    """
    state: dict[str, Any] = {
        "submission_return": None,
        "rubric_return": None,
        "progress_return": None,
        "status_return": None,
        "submission_calls": [],
        "rubric_calls": [],
        "progress_calls": [],
        "status_calls": [],
        "call_order": [],
    }

    async def _stub_submission(args: Any) -> Any:
        state["submission_calls"].append(args)
        state["call_order"].append("read_capstone_submission_content")
        return state["submission_return"]

    async def _stub_rubric(args: Any) -> Any:
        state["rubric_calls"].append(args)
        state["call_order"].append("read_rubric_for_capstone")
        return state["rubric_return"]

    async def _stub_progress(args: Any) -> Any:
        state["progress_calls"].append(args)
        state["call_order"].append("read_student_full_progress")
        return state["progress_return"]

    async def _stub_status(args: Any) -> Any:
        state["status_calls"].append(args)
        state["call_order"].append("read_capstone_status")
        return state["status_return"]

    for name, stub_func in (
        ("read_capstone_submission_content", _stub_submission),
        ("read_rubric_for_capstone", _stub_rubric),
        ("read_student_full_progress", _stub_progress),
        ("read_capstone_status", _stub_status),
    ):
        spec = registry.get(name)
        new_spec = replace(spec, func=stub_func)
        monkeypatch.setitem(registry._tools, name, new_spec)

    return state


# ── JSON output builders ───────────────────────────────────────────


def _happy_output(
    *,
    overall_score: float = 0.85,
    rubric_available: bool = True,
    dimensions: int = 3,
    title: str = "RAG Capstone Eval",
    handoff_request: dict | None = None,
    extra_top_level: dict | None = None,
    narrative: str = "Specific feedback referencing src/agents/retriever.py and the PR.",
) -> str:
    payload: dict[str, Any] = {
        "overall_score": overall_score,
        "dimension_scores": [
            {
                "dimension_name": f"dimension_{i}",
                "rubric_criterion": f"rubric criterion text {i}",
                "score": 0.8,
                "evidence": f"evidence pointing to file_{i}.py",
            }
            for i in range(dimensions)
        ],
        "narrative_feedback": narrative,
        "portfolio_entry_draft": {
            "title": title,
            "summary": "Summary of the capstone for portfolio.",
            "key_strengths": ["Working RAG over docs", "Eval harness present"],
            "artifacts_referenced": [
                "https://github.com/example/pr/42",
                "src/agents/retriever.py",
            ],
        },
        "rubric_available": rubric_available,
        "handoff_request": handoff_request,
    }
    if extra_top_level:
        payload.update(extra_top_level)
    return json.dumps(payload)


def _refusal_output(
    *,
    title: str,
    narrative: str,
    handoff_request: dict | None = None,
) -> str:
    return json.dumps(
        {
            "overall_score": 0.0,
            "dimension_scores": [],
            "narrative_feedback": narrative,
            "portfolio_entry_draft": {
                "title": title,
                "summary": narrative,
                "key_strengths": [],
                "artifacts_referenced": [],
            },
            "rubric_available": False,
            "handoff_request": handoff_request,
        }
    )


def _capstone_submission_dict(
    *,
    is_capstone: bool = True,
    found: bool = True,
    student_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Build a ReadCapstoneSubmissionContentOutput-shape dict via the
    real schema so .model_dump() works."""
    from app.agents.tools.agent_specific.project_evaluator.read_capstone_submission_content import (
        ReadCapstoneSubmissionContentOutput,
    )

    if not found:
        return ReadCapstoneSubmissionContentOutput(found=False).model_dump(mode="json")

    return ReadCapstoneSubmissionContentOutput(
        found=True,
        submission_id=uuid.uuid4(),
        student_id=student_id or uuid.uuid4(),
        exercise_id=uuid.uuid4(),
        code="def retriever(): ...",
        github_pr_url="https://github.com/example/pr/42",
        self_explanation="I built a vector index over docs.",
        feedback=None,
        ai_feedback=None,
        score=None,
        status="submitted",
        exercise_title="RAG Capstone",
        exercise_description="Build a working RAG pipeline.",
        is_capstone=is_capstone,
    ).model_dump(mode="json")


def _rubric_dict(*, has_rubric: bool = True, is_capstone: bool = True) -> dict[str, Any]:
    from app.agents.tools.agent_specific.project_evaluator.read_rubric_for_capstone import (
        ReadRubricForCapstoneOutput,
    )

    rubric = (
        {"architecture": "Does it use RAG?", "completeness": "Done?"}
        if has_rubric
        else None
    )
    text = json.dumps(rubric, indent=2) if rubric else None
    return ReadRubricForCapstoneOutput(
        found=True,
        rubric_json=rubric,
        rubric_text=text,
        is_capstone=is_capstone,
        exercise_title="RAG Capstone",
    ).model_dump(mode="json")


def _empty_progress_dict() -> dict[str, Any]:
    from app.agents.tools.agent_specific.career_coach.read_student_full_progress import (
        ReadStudentFullProgressOutput,
    )

    return ReadStudentFullProgressOutput(
        courses=[],
        total_lessons_completed=0,
        total_exercise_submissions=0,
    ).model_dump(mode="json")


def _empty_capstone_status_dict() -> dict[str, Any]:
    from app.agents.tools.agent_specific.career_coach.read_capstone_status import (
        ReadCapstoneStatusOutput,
    )

    return ReadCapstoneStatusOutput(capstone=None, has_capstone=False).model_dump(mode="json")


# ── Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_with_rubric(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """All 4 tools fire BEFORE LLM call; LLM returns valid output;
    schema validates."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=True)
    patch_tools["rubric_return"] = _rubric_dict(has_rubric=True)
    patch_tools["progress_return"] = _empty_progress_dict()
    patch_tools["status_return"] = _empty_capstone_status_dict()

    stub = patch_llm(_happy_output())

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    # All 4 tools fired
    assert len(patch_tools["submission_calls"]) == 1
    assert len(patch_tools["rubric_calls"]) == 1
    assert len(patch_tools["progress_calls"]) == 1
    assert len(patch_tools["status_calls"]) == 1
    # LLM fired exactly once, AFTER all reads
    assert len(stub.calls) == 1

    # Tool order: submission first, then rubric, then progress + status
    order = patch_tools["call_order"]
    assert order[0] == "read_capstone_submission_content"
    assert order[1] == "read_rubric_for_capstone"
    assert "read_student_full_progress" in order[2:]
    assert "read_capstone_status" in order[2:]

    # Output validates as rubric-grounded
    assert payload["rubric_available"] is True
    assert len(payload["dimension_scores"]) == 3
    assert "answer" in payload
    assert "/100" in payload["answer"]


@pytest.mark.asyncio
async def test_d4_early_exit_on_non_capstone(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """D-4 early exit: is_capstone=False → rubric/progress/status NOT
    called; LLM receives NON_CAPSTONE_SUBMISSION marker."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=False)

    stub = patch_llm(
        _refusal_output(
            title="Not a Capstone Submission",
            narrative=(
                "Submitted work is not a capstone-tier project. "
                "project_evaluator evaluates capstone submissions only."
            ),
            handoff_request={
                "target_agent": "senior_engineer",
                "reason": "non-capstone code review",
                "suggested_context": {"submission_id": str(sid)},
            },
        )
    )

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    # Only the submission tool was called
    assert len(patch_tools["submission_calls"]) == 1
    assert len(patch_tools["rubric_calls"]) == 0
    assert len(patch_tools["progress_calls"]) == 0
    assert len(patch_tools["status_calls"]) == 0

    # LLM fired with NON_CAPSTONE_SUBMISSION marker in user_block
    assert NON_CAPSTONE_SUBMISSION_MARKER in stub.last_user_block()

    # Refusal-shape invariants enforced
    assert payload["rubric_available"] is False
    assert payload["dimension_scores"] == []
    assert payload["overall_score"] == 0.0

    # D-4 handoff to senior_engineer preserved
    hr = payload["handoff_request"]
    assert hr is not None
    assert hr["target_agent"] == "senior_engineer"
    assert isinstance(hr["suggested_context"], dict)


@pytest.mark.asyncio
async def test_d4_early_exit_on_submission_not_found(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """found=False is symmetric with is_capstone=False — both are
    architectural-contract violations routed to refusal."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(found=False)

    stub = patch_llm(
        _refusal_output(
            title="Not a Capstone Submission",
            narrative="Submitted work is not a capstone-tier project.",
        )
    )

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    assert len(patch_tools["rubric_calls"]) == 0
    assert NON_CAPSTONE_SUBMISSION_MARKER in stub.last_user_block()
    assert payload["rubric_available"] is False
    assert payload["dimension_scores"] == []


@pytest.mark.asyncio
async def test_de_rubric_unavailable_marker(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """D-E rubric unavailable: rubric_text=None → user_block contains
    RUBRIC_UNAVAILABLE marker; runtime forces refusal invariants
    even if LLM produces other shapes."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=True)
    patch_tools["rubric_return"] = _rubric_dict(has_rubric=False)
    patch_tools["progress_return"] = _empty_progress_dict()
    patch_tools["status_return"] = _empty_capstone_status_dict()

    # LLM "forgets" the marker and produces a populated output anyway —
    # runtime backstop must clamp it to refusal shape.
    stub = patch_llm(_happy_output(rubric_available=True, dimensions=3))

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    # User block contained the RUBRIC_UNAVAILABLE marker
    assert RUBRIC_UNAVAILABLE_MARKER in stub.last_user_block()

    # Runtime backstop forced refusal invariants
    assert payload["rubric_available"] is False
    assert payload["dimension_scores"] == []
    assert payload["handoff_request"] is None


@pytest.mark.asyncio
async def test_runtime_backstop_rubric_available_with_empty_dimensions(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """If LLM claims rubric_available=True but produces empty
    dimension_scores, runtime forces rubric_available=False (the
    contradiction is the load-bearing D-E enforcement gap signal)."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=True)
    patch_tools["rubric_return"] = _rubric_dict(has_rubric=True)
    patch_tools["progress_return"] = _empty_progress_dict()
    patch_tools["status_return"] = _empty_capstone_status_dict()

    patch_llm(_happy_output(rubric_available=True, dimensions=0))

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    assert payload["rubric_available"] is False
    assert payload["dimension_scores"] == []


@pytest.mark.asyncio
async def test_extra_top_level_field_stripped(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """strip_extra_fields drops top-level extras (Bug 23 regression
    pattern from D13)."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=True)
    patch_tools["rubric_return"] = _rubric_dict(has_rubric=True)
    patch_tools["progress_return"] = _empty_progress_dict()
    patch_tools["status_return"] = _empty_capstone_status_dict()

    patch_llm(_happy_output(extra_top_level={"approved": True, "rogue_field": "x"}))

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    assert "approved" not in payload
    assert "rogue_field" not in payload


@pytest.mark.asyncio
async def test_narrative_feedback_overshoot_truncated(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """truncate_to_schema clips narrative_feedback to ≤5000 chars
    (Bug 17 regression pattern from D13)."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=True)
    patch_tools["rubric_return"] = _rubric_dict(has_rubric=True)
    patch_tools["progress_return"] = _empty_progress_dict()
    patch_tools["status_return"] = _empty_capstone_status_dict()

    long_narrative = "x" * 5500
    patch_llm(_happy_output(narrative=long_narrative))

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    assert len(payload["narrative_feedback"]) <= 5000


@pytest.mark.asyncio
async def test_handoff_request_dict_suggested_context_validates(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """Bug 21 regression: HandoffRequest.suggested_context as dict
    validates."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=False)

    patch_llm(
        _refusal_output(
            title="Not a Capstone Submission",
            narrative="Refusal narrative.",
            handoff_request={
                "target_agent": "senior_engineer",
                "reason": "non-capstone code review",
                "suggested_context": {"submission_id": str(sid)},
            },
        )
    )

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    assert payload["handoff_request"] is not None
    assert isinstance(payload["handoff_request"]["suggested_context"], dict)


@pytest.mark.asyncio
async def test_handoff_request_string_suggested_context_rejected(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """Bug 21 regression: HandoffRequest.suggested_context as string
    must be rejected by schema. _parse_output raises (or runtime
    falls through to a downstream error). We assert the agent does
    NOT silently accept the bad shape."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=False)

    patch_llm(
        json.dumps(
            {
                "overall_score": 0.0,
                "dimension_scores": [],
                "narrative_feedback": "Refusal narrative.",
                "portfolio_entry_draft": {
                    "title": "Not a Capstone Submission",
                    "summary": "Refusal narrative.",
                    "key_strengths": [],
                    "artifacts_referenced": [],
                },
                "rubric_available": False,
                "handoff_request": {
                    "target_agent": "senior_engineer",
                    "reason": "non-capstone code review",
                    "suggested_context": (
                        '{"submission_id": "' + str(sid) + '"}'
                    ),  # JSON-encoded STRING — Bug 21 regression shape
                },
            }
        )
    )

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    with pytest.raises(Exception):
        await agent.run(inp, stub_ctx)


@pytest.mark.asyncio
async def test_de_refusal_handoff_request_forced_null(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """D-E refusal: even if LLM populates handoff_request, runtime
    backstop forces it to None (D-E refusal must NOT handoff;
    only D-4 refusal handoffs to senior_engineer)."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=True)
    patch_tools["rubric_return"] = _rubric_dict(has_rubric=False)
    patch_tools["progress_return"] = _empty_progress_dict()
    patch_tools["status_return"] = _empty_capstone_status_dict()

    patch_llm(
        _happy_output(
            handoff_request={
                "target_agent": "senior_engineer",
                "reason": "non-capstone code review",
                "suggested_context": {"submission_id": str(sid)},
            }
        )
    )

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    payload = await agent.run(inp, stub_ctx)

    # D-E refusal: handoff_request forced None
    assert payload["handoff_request"] is None


@pytest.mark.asyncio
async def test_d4_refusal_does_not_call_extra_tools_in_order(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """Tool ordering on D-4 path: ONLY submission tool fires; LLM call
    happens AFTER it."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=False)

    stub = patch_llm(
        _refusal_output(
            title="Not a Capstone Submission",
            narrative="Refusal narrative.",
        )
    )

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    await agent.run(inp, stub_ctx)

    assert patch_tools["call_order"] == ["read_capstone_submission_content"]
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_happy_path_user_block_includes_rubric_text(
    stub_ctx: AgentContext,
    patch_active_session: None,
    patch_executor_audit: None,
    patch_tools: dict[str, Any],
    patch_llm: Any,
) -> None:
    """When rubric is present, user_block contains the JSON-pretty
    rubric_text and DOES NOT contain the RUBRIC_UNAVAILABLE marker."""
    sid = uuid.uuid4()
    patch_tools["submission_return"] = _capstone_submission_dict(is_capstone=True)
    patch_tools["rubric_return"] = _rubric_dict(has_rubric=True)
    patch_tools["progress_return"] = _empty_progress_dict()
    patch_tools["status_return"] = _empty_capstone_status_dict()

    stub = patch_llm(_happy_output())

    agent = ProjectEvaluatorAgent()
    inp = ProjectEvaluatorInput(project_submission_id=sid)
    await agent.run(inp, stub_ctx)

    user_block = stub.last_user_block()
    assert RUBRIC_UNAVAILABLE_MARKER not in user_block
    assert NON_CAPSTONE_SUBMISSION_MARKER not in user_block
    assert "architecture" in user_block  # rubric content present
