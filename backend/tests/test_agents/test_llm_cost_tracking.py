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
