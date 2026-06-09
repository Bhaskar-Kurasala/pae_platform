"""PR3/C7.1 — per-LLM-call cost tracking tests.

Confirms that BaseAgent.log_action emits a structured `llm.call` event
with the spec'd shape AND calls into the PostHog telemetry shim, so the
dashboard query `SUM(cost_estimate_usd) BY user_id` is feedable.

We exercise the path end-to-end with a minimal BaseAgent subclass that
populates state.metadata with the usage shape LangChain emits, then
captures stdout (where structlog renders) and the telemetry capture
mock to make assertions.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.base_agent import AgentState, BaseAgent


class _FakeAgent(BaseAgent):
    """BaseAgent subclass that pretends to call an LLM."""

    name = "fake_test_agent"
    description = "test"
    trigger_conditions = []
    model = "claude-sonnet-4-6"

    async def execute(self, state: AgentState) -> AgentState:
        # Mimic what real agents do — populate state.metadata with token
        # counts via _merge_token_usage. We bypass the LLM and inject
        # the fake response directly.
        class _FakeAIMessage:
            usage_metadata = {"input_tokens": 100, "output_tokens": 200}

        state = self._merge_token_usage(state, _FakeAIMessage())
        return state.model_copy(update={"response": "fake response"})


@pytest.mark.asyncio
async def test_llm_call_event_logged_with_cost(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful agent run emits an `llm.call` structlog event with
    tokens, duration, agent_name, model, user_id, AND a cost estimate
    in both USD and INR."""
    # log_action also writes to the DB; mock that so we don't need a
    # session in this unit test.
    async def _noop_log_to_db(self: Any, *args: Any, **kwargs: Any) -> None:
        return None

    # Patch the inner DB write to a no-op; we only care about the log
    # line and the telemetry call.
    captured_telemetry: list[tuple[str | None, str, dict[str, Any]]] = []

    def fake_capture(
        distinct_id: str | None,
        event: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        captured_telemetry.append((distinct_id, event, properties or {}))

    # The base_agent imports telemetry inside log_action, so we need to
    # intercept the import target.
    import app.core.telemetry as telemetry_mod

    monkeypatch.setattr(telemetry_mod, "capture", fake_capture)

    # Replace the DB write portion: monkeypatch AsyncSessionLocal to
    # a context manager whose session.add + commit are no-ops.
    class _NoopSession:
        async def __aenter__(self) -> "_NoopSession":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        def add(self, *_: Any, **__: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "AsyncSessionLocal", lambda: _NoopSession())

    agent = _FakeAgent()
    state = AgentState(student_id="user-42", task="hello")
    state = await agent.execute(state)
    await agent.log_action(state, status="completed", duration_ms=512)

    out = capsys.readouterr().out

    # The structlog event must include all spec'd fields.
    assert "llm.call" in out
    assert "fake_test_agent" in out
    assert "claude-sonnet-4-6" in out
    assert '"tokens_in": 100' in out
    assert '"tokens_out": 200' in out
    assert '"duration_ms": 512' in out
    assert "user-42" in out
    # Cost: 100 in + 200 out at sonnet rates → (100/1M * $3) + (200/1M * $15)
    # = $0.0003 + $0.003 = $0.0033 → INR ≈ 0.2772
    assert "cost_estimate_usd" in out
    assert "cost_estimate_inr" in out

    # And the same payload should have been forwarded to telemetry.
    assert len(captured_telemetry) == 1
    distinct_id, event_name, props = captured_telemetry[0]
    assert distinct_id == "user-42"
    assert event_name == "llm.call"
    assert props["agent_name"] == "fake_test_agent"
    assert props["tokens_in"] == 100
    assert props["tokens_out"] == 200
    assert props["cost_estimate_usd"] > 0
    assert props["cost_estimate_inr"] > 0


@pytest.mark.asyncio
async def test_llm_call_event_skipped_when_no_token_usage(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the agent didn't actually call an LLM (no usage in metadata),
    we don't emit a fake `llm.call` event with zero tokens. That would
    pollute the PostHog dashboard with stub agents (spaced_repetition,
    knowledge_graph, etc.) that compute SM-2 in pure Python."""
    captured_telemetry: list[tuple[str | None, str, dict[str, Any]]] = []
    import app.core.telemetry as telemetry_mod

    monkeypatch.setattr(
        telemetry_mod,
        "capture",
        lambda distinct_id, event, properties=None: captured_telemetry.append(
            (distinct_id, event, properties or {})
        ),
    )

    class _NoopSession:
        async def __aenter__(self) -> "_NoopSession":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        def add(self, *_: Any, **__: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "AsyncSessionLocal", lambda: _NoopSession())

    class _NoLLMAgent(BaseAgent):
        name = "no_llm"
        description = "no llm"
        trigger_conditions: list[str] = []
        model = "n/a"

        async def execute(self, state: AgentState) -> AgentState:
            # Don't populate token usage.
            return state.model_copy(update={"response": "computed"})

    agent = _NoLLMAgent()
    state = AgentState(student_id="user-1", task="x")
    state = await agent.execute(state)
    await agent.log_action(state, status="completed", duration_ms=10)

    out = capsys.readouterr().out
    assert "llm.call" not in out
    assert captured_telemetry == []


@pytest.mark.asyncio
async def test_unknown_model_falls_back_to_zero_cost(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown model id (e.g. a self-hosted MiniMax variant) falls back
    to cost = 0 rather than crashing or emitting nonsense — the
    absolute ₹20 cost cap covers the actual budget protection."""
    import app.core.telemetry as telemetry_mod

    monkeypatch.setattr(telemetry_mod, "capture", lambda *a, **k: None)

    class _NoopSession:
        async def __aenter__(self) -> "_NoopSession":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        def add(self, *_: Any, **__: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "AsyncSessionLocal", lambda: _NoopSession())

    class _MysteryModelAgent(BaseAgent):
        name = "mystery_agent"
        description = ""
        trigger_conditions: list[str] = []
        model = "minimax-m-2.7-self-hosted"  # not in pricing table

        async def execute(self, state: AgentState) -> AgentState:
            class _FakeAIMessage:
                usage_metadata = {"input_tokens": 50, "output_tokens": 75}

            state = self._merge_token_usage(state, _FakeAIMessage())
            return state.model_copy(update={"response": "ok"})

    agent = _MysteryModelAgent()
    state = AgentState(student_id="user-9", task="x")
    state = await agent.execute(state)
    await agent.log_action(state, status="completed", duration_ms=100)

    out = capsys.readouterr().out
    # Event still emitted (we still want the duration/token metric).
    assert "llm.call" in out
    # But cost is zero.
    assert '"cost_estimate_usd": 0' in out
    assert '"cost_estimate_inr": 0' in out


# ── MiniMax M2.7 activation — pricing + dynamic model_name resolution ──
#
# Both tests below pin the contract that AgenticBaseAgent's cost
# tracking is honest under MiniMax routing: the pricing table covers
# MiniMax-M2.7, and _finalize_action_log writes the model the live
# response reported (not the agent's ClassVar default).


def test_estimate_cost_inr_minimax_pricing_nonzero() -> None:
    """Regression against the silent-zero gap: estimate_cost_inr must
    return a nonzero value for MiniMax-M2.7 with realistic token counts.

    This is the symptom that would have surfaced if the pricing table
    weren't updated alongside MiniMax activation — every audit row
    would silently emit cost_inr=0 and per-feature financial reporting
    would lie. Sonnet must also stay nonzero (the change shouldn't
    regress the existing model entries).
    """
    from app.agents.llm_factory import estimate_cost_inr

    # 2k input + 500 output is a realistic billing_support short-call shape.
    minimax_cost = estimate_cost_inr(
        model="MiniMax-M2.7", input_tokens=2000, output_tokens=500
    )
    sonnet_cost = estimate_cost_inr(
        model="claude-sonnet-4-6", input_tokens=2000, output_tokens=500
    )

    assert minimax_cost > 0, "MiniMax-M2.7 must have pricing — silent zero is the bug"
    assert sonnet_cost > 0, "Sonnet pricing must not regress"
    # MiniMax is roughly 10x cheaper than Sonnet at these rates; the
    # ratio shouldn't invert without an explicit pricing-table change.
    assert minimax_cost < sonnet_cost


@pytest.mark.asyncio
async def test_finalize_action_log_writes_actual_model_under_minimax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a live response reports model="MiniMax-M2.7", the audit row
    must record THAT (not the agent's ClassVar default), and cost_inr
    must be computed against MiniMax pricing.

    Also pins the fallback: when no LLM call happened (empty
    accumulator), resolved_model falls back to self.model_name and
    cost_inr stays at 0 — no silent overcharge for safety-blocked paths.
    """
    import uuid as _uuid
    from typing import Any
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.agents.agentic_base import AgenticBaseAgent, AgentContext, CallChain

    captured: dict[str, Any] = {}

    class _CapturingSession:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, row: Any) -> None:
            self.added.append(row)

        async def commit(self) -> None:
            captured["row"] = self.added[-1]

        async def __aenter__(self) -> "_CapturingSession":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    # AsyncSessionLocal is imported lazily inside _finalize_action_log
    # (`from app.core.database import AsyncSessionLocal`) — patch the
    # source module so the lazy import resolves to our capturer.
    monkeypatch.setattr(
        "app.core.database.AsyncSessionLocal",
        lambda: _CapturingSession(),
    )

    # Concrete agent — only need access to the protected helpers.
    class _TestAgent(AgenticBaseAgent):  # type: ignore[misc]
        name = "test_minimax_attribution"
        description = "test"
        model_name = "claude-haiku-4-5"  # the agent's *intended* default

        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    agent = _TestAgent()
    ctx = AgentContext(
        user_id=_uuid.uuid4(),
        chain=CallChain.start_root(caller="test"),
        session=MagicMock(spec=AsyncSession),
        extra={"_llm_usage": []},
    )

    # ── Path 1: live response reports MiniMax — accumulator captures it ──
    fake_response = MagicMock()
    fake_response.usage_metadata = {"input_tokens": 2000, "output_tokens": 500}
    fake_response.response_metadata = {"model": "MiniMax-M2.7"}
    agent._track_llm_usage(ctx, fake_response)

    assert ctx.extra["_llm_usage"][-1]["model"] == "MiniMax-M2.7"

    import time as _time
    await agent._finalize_action_log(
        ctx=ctx,
        output={"answer": "hello"},
        status="completed",
        error_message=None,
        started_at=_time.perf_counter() - 0.1,
    )

    row = captured["row"]
    assert row.output_data["llm"]["model"] == "MiniMax-M2.7", (
        "Audit row must record the model that ACTUALLY ran, "
        "not the agent's ClassVar intent"
    )
    assert row.cost_inr is not None and float(row.cost_inr) > 0, (
        "cost_inr must be nonzero — pricing table covers MiniMax-M2.7"
    )

    # ── Path 2: no LLM call (safety-blocked) — fallback to ClassVar, ₹0 ──
    captured.clear()
    ctx2 = AgentContext(
        user_id=_uuid.uuid4(),
        chain=CallChain.start_root(caller="test"),
        session=MagicMock(spec=AsyncSession),
        extra={"_llm_usage": []},
    )
    await agent._finalize_action_log(
        ctx=ctx2,
        output=None,
        status="blocked",
        error_message="safety",
        started_at=_time.perf_counter() - 0.05,
    )

    row2 = captured["row"]
    assert row2.output_data["llm"]["model"] == "claude-haiku-4-5", (
        "Empty accumulator → fall back to self.model_name (intent)"
    )
    assert row2.cost_inr is None, "No LLM call → no silent overcharge"


# ── D12 CP3 Part C — tailored_resume_llm live-model extraction ────────
#
# Pins the fix for the under-cost bug: generate() must return the model
# id that the live LLM response actually reports (response_metadata["model"])
# rather than the static model_for("smart") sentinel. When MiniMax runs,
# "model" in response_metadata is "MiniMax-M2.7"; the old code would
# return "claude-sonnet-4-6" regardless, causing Sonnet pricing to be
# applied to a MiniMax call (under-cost, not silent-zero).


@pytest.mark.asyncio
async def test_tailored_resume_llm_generate_uses_live_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate() must return the model from response_metadata, not model_for('smart').

    When the live response reports model="MiniMax-M2.7", the returned
    dict's "model" key must be "MiniMax-M2.7" so the caller can apply
    correct MiniMax pricing. Before the D12 CP3 Part C fix, this would
    return "claude-sonnet-4-6" unconditionally.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.tailored_resume_llm import TailoredResumeAgent

    # Fake LLM response shaped like a real langchain response under MiniMax.
    fake_response = MagicMock()
    fake_response.content = '{"sections": [], "headline": "test"}'
    fake_response.usage_metadata = {"input_tokens": 500, "output_tokens": 200}
    fake_response.response_metadata = {"model": "MiniMax-M2.7"}

    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)

    # Patch build_llm to return our fake; also patch extract_json_object
    # so the raw text parses cleanly without real JSON.
    monkeypatch.setattr(
        "app.agents.tailored_resume_llm.build_llm",
        lambda **_kwargs: fake_llm,
    )
    monkeypatch.setattr(
        "app.agents.tailored_resume_llm.extract_json_object",
        lambda _raw: {"sections": [], "headline": "test"},
    )

    agent = TailoredResumeAgent()
    result = await agent.generate(
        evidence={"skills": ["Python"]},
        parsed_jd={"role": "ML Engineer"},
        evidence_allowlist={"skill:Python"},
    )

    assert result["model"] == "MiniMax-M2.7", (
        f"Expected 'MiniMax-M2.7' from response_metadata, got {result['model']!r}. "
        "This is the D12 CP3 Part C under-cost bug: static model_for('smart') "
        "was returned instead of the live response model."
    )
    assert result["input_tokens"] == 500
    assert result["output_tokens"] == 200


@pytest.mark.asyncio
async def test_tailored_resume_llm_falls_back_when_no_response_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When response_metadata is absent or empty, fall back to model_for('smart').

    This covers stub LLMs and providers that don't emit response_metadata —
    the fallback must not crash, and must return a non-empty model string.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.tailored_resume_llm import TailoredResumeAgent

    fake_response = MagicMock()
    fake_response.content = '{"sections": [], "headline": "test"}'
    fake_response.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
    # No response_metadata attribute at all — getattr returns {}.
    del fake_response.response_metadata

    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)

    monkeypatch.setattr(
        "app.agents.tailored_resume_llm.build_llm",
        lambda **_kwargs: fake_llm,
    )
    monkeypatch.setattr(
        "app.agents.tailored_resume_llm.extract_json_object",
        lambda _raw: {"sections": [], "headline": "test"},
    )

    agent = TailoredResumeAgent()
    result = await agent.generate(
        evidence={"skills": ["Python"]},
        parsed_jd={"role": "ML Engineer"},
        evidence_allowlist={"skill:Python"},
    )

    # Fallback should be the static Sonnet name — non-empty, not None.
    assert isinstance(result["model"], str) and len(result["model"]) > 0


# ── D17b/ITEM 1 — readiness sub-agents capture model from response ─────
#
# The institutional under-cost bug from D12 CP3 (tailored_resume_llm)
# was previously fixed at the LLM-result-dict layer. ITEM 1 closes the
# same shape one architectural layer up: SubAgentResult/ParsedJd
# constructions in readiness_sub_agents.py + jd_parser.py used to
# hardcode model=model_for(self.tier), recording intent (Anthropic
# default) instead of the actually-routed model (MiniMax M2.7 when
# MINIMAX_API_KEY is set). Fix uses the new _model_from(response)
# helper at success-path constructions; error paths intentionally
# retain model_for(self.tier) because no response exists yet.


@pytest.mark.asyncio
async def test_readiness_sub_agent_captures_response_model_under_minimax() -> None:
    """JDAnalyst.run() success path → SubAgentResult.model = response_metadata['model'].

    Pins the under-cost fix at the readiness sub-agent layer. With a
    fake response reporting model='MiniMax-M2.7', the returned
    SubAgentResult.model must echo MiniMax-M2.7, NOT model_for('fast')
    (which would be claude-haiku-4-5).
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.readiness_sub_agents import JDAnalyst

    fake_response = MagicMock()
    fake_response.content = '{"role": "ML Engineer", "must_haves": []}'
    fake_response.usage_metadata = {"input_tokens": 120, "output_tokens": 80}
    fake_response.response_metadata = {"model": "MiniMax-M2.7"}

    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)

    import app.agents.readiness_sub_agents as rsa

    original_build = rsa.build_llm
    rsa.build_llm = lambda **_k: fake_llm  # type: ignore[assignment]
    try:
        agent = JDAnalyst()
        result = await agent.run(jd_text="a sample JD body", parsed_jd={})
    finally:
        rsa.build_llm = original_build  # type: ignore[assignment]

    assert result.succeeded
    assert result.model == "MiniMax-M2.7", (
        f"Expected MiniMax-M2.7 from response_metadata; got {result.model!r}"
    )


@pytest.mark.asyncio
async def test_readiness_sub_agent_falls_back_to_intent_when_no_response_metadata() -> None:
    """When response_metadata is absent (stub LLM), fall back to model_for(tier).

    Discipline: intent is the most honest signal when truth is
    unavailable. Stub LLMs in tests, providers without metadata, etc.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.llm_factory import model_for
    from app.agents.readiness_sub_agents import JDAnalyst

    fake_response = MagicMock()
    fake_response.content = '{"role": "ML Engineer", "must_haves": []}'
    fake_response.usage_metadata = {"input_tokens": 50, "output_tokens": 25}
    fake_response.response_metadata = {}  # empty — no model key

    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)

    import app.agents.readiness_sub_agents as rsa

    original_build = rsa.build_llm
    rsa.build_llm = lambda **_k: fake_llm  # type: ignore[assignment]
    try:
        agent = JDAnalyst()
        result = await agent.run(jd_text="a sample JD body", parsed_jd={})
    finally:
        rsa.build_llm = original_build  # type: ignore[assignment]

    assert result.succeeded
    # JDAnalyst.tier = "smart" → model_for("smart") = "claude-sonnet-4-6"
    assert result.model == model_for("smart")


@pytest.mark.asyncio
async def test_readiness_sub_agent_error_path_keeps_intent_model() -> None:
    """Error path (LLM raises before response) keeps model=model_for(self.tier).

    Discipline preserved: success/error asymmetry is load-bearing.
    No response means no truth to extract; intent is the honest
    signal of what the agent TRIED to use. The fix MUST NOT touch
    the error-path constructions — they would otherwise lose all
    model attribution.
    """
    from unittest.mock import AsyncMock

    from app.agents.llm_factory import model_for
    from app.agents.readiness_sub_agents import JDAnalyst

    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(
        side_effect=RuntimeError("simulated provider 503")
    )

    import app.agents.readiness_sub_agents as rsa

    original_build = rsa.build_llm
    rsa.build_llm = lambda **_k: fake_llm  # type: ignore[assignment]
    try:
        agent = JDAnalyst()
        result = await agent.run(jd_text="a sample JD body", parsed_jd={})
    finally:
        rsa.build_llm = original_build  # type: ignore[assignment]

    assert not result.succeeded
    assert result.error and "503" in result.error
    # Intent fallback on error — no response existed.
    # JDAnalyst.tier = "smart" → model_for("smart") = "claude-sonnet-4-6"
    assert result.model == model_for("smart")


@pytest.mark.asyncio
async def test_jd_parser_captures_response_model_under_minimax() -> None:
    """jd_parser.parse_jd() success path → ParsedJd.model = response_metadata['model'].

    Same fix shape as readiness sub-agents but applied inline to
    jd_parser (which mirrors the inline usage_metadata extraction
    style rather than importing the helper).
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.services import jd_parser

    fake_response = MagicMock()
    fake_response.content = '{"role": "ML Engineer", "company": "Acme"}'
    fake_response.usage_metadata = {"input_tokens": 200, "output_tokens": 60}
    fake_response.response_metadata = {"model": "MiniMax-M2.7"}

    async def _fake_invoke(_jd_text: str):
        return jd_parser.normalize_llm_content(fake_response.content), fake_response

    original_invoke = jd_parser._invoke_llm
    jd_parser._invoke_llm = _fake_invoke  # type: ignore[assignment]
    try:
        parsed = await jd_parser.parse_jd("Senior ML Engineer at Acme...")
    finally:
        jd_parser._invoke_llm = original_invoke  # type: ignore[assignment]

    # Sanity: parse succeeded (non-empty role)
    assert parsed.role == "ML Engineer"
    assert parsed.company == "Acme"
    # The fix: ParsedJd.model echoes the live response, not model_for("fast")
    assert parsed.model == "MiniMax-M2.7", (
        f"Expected MiniMax-M2.7 from response_metadata; got {parsed.model!r}"
    )
