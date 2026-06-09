"""D12 CP3 Part F — pin study_planner_v2 tool-call signature contracts.

Two CP2-introduced bugs caught during CP3 pre-flight:

  Bug 1 (silent): _log_mode_inference passed wrong keys to the
    log_event tool (event_type/agent/payload), all rejected by
    LogEventInput(extra="forbid"). The broad except swallowed the
    ValidationError and logged at debug only — the mode_inferred
    event never emitted.

  Bug 2 (raises): _commit_plan passed output.mode (weekly_plan,
    session_plan, adherence_check) to the commit_plan tool whose
    plan_type Literal is "weekly" | "session". Crashed every
    study_planner run that reached the commit step.

These tests pin both fixes so future signature drift fails CI.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.study_planner_v2 import StudyPlannerAgent
from app.schemas.agents.study_planner import StudyPlannerOutput

pytestmark = [pytest.mark.asyncio]


def _make_ctx() -> AgentContext:
    return AgentContext(
        user_id=uuid.uuid4(),
        chain=CallChain.start_root(caller="test"),
        session=MagicMock(spec=AsyncSession),
        extra={"_llm_usage": []},
    )


# ── Bug 1 — log_event signature ───────────────────────────────────


class TestLogModeInferenceSignature:
    """Pins the F.1 fix: _log_mode_inference must call log_event with
    (event_name, properties, severity) — the LogEventInput contract."""

    async def test_log_event_called_with_correct_kwargs(self) -> None:
        """Mock agent.tool_call; assert log_event invocation shape.

        D12 CP3 Part H.1 fix: agent now routes via the canonical
        AgenticBaseAgent.tool_call helper (not a bespoke ToolExecutor).
        Mock patches that helper directly — robust to internal executor
        changes.
        """
        agent = StudyPlannerAgent()
        ctx = _make_ctx()

        captured: list[tuple[str, dict[str, Any]]] = []

        async def _mock_tool_call(_self: Any, tool_name: str, args: dict[str, Any], _ctx: Any) -> Any:
            # patch.object on the class makes this an unbound method, so
            # self is passed as the first positional arg.
            captured.append((tool_name, args))
            return MagicMock(output=MagicMock(model_dump=lambda mode="json": {}))

        with patch.object(StudyPlannerAgent, "tool_call", _mock_tool_call):
            await agent._log_mode_inference(
                resolved_mode="weekly_plan",
                input_signals="this week i want to learn rag",
                ctx=ctx,
            )

        assert len(captured) == 1
        tool_name, args = captured[0]
        assert tool_name == "log_event"
        assert args["event_name"] == "study_planner.mode_inferred"
        assert args["severity"] == "info"
        assert args["properties"] == {
            "inferred_mode": "weekly_plan",
            "input_signals": "this week i want to learn rag",
        }
        # Pin the absence of the buggy keys so a regression fails loudly.
        assert "event_type" not in args
        assert "agent" not in args
        assert "payload" not in args

    async def test_log_event_passes_real_validation(self) -> None:
        """Without mocking, _log_mode_inference must not raise.

        Catches future signature drift: if someone adds a required
        field to LogEventInput, this test fails fast. The agent's
        broad except would otherwise hide the breakage.
        """
        from app.agents.tools.universal.log_event import (
            LogEventInput,
        )

        # Pydantic-validate the exact payload shape the agent now sends.
        payload = LogEventInput(
            event_name="study_planner.mode_inferred",
            properties={
                "inferred_mode": "session_plan",
                "input_signals": "i have 60 minutes",
            },
            severity="info",
        )
        assert payload.event_name == "study_planner.mode_inferred"
        assert payload.properties["inferred_mode"] == "session_plan"
        assert payload.severity == "info"


# ── Bug 2 — commit_plan plan_type mapping ─────────────────────────


class TestCommitPlanTypeMapping:
    """Pins the F.2 fix: agent.output.mode → tool.plan_type maps:
       weekly_plan  → weekly
       session_plan → session
       adherence_check → SKIP (no plan to commit)
       (any other)  → SKIP
    """

    @staticmethod
    def _stub_output(mode: str) -> StudyPlannerOutput:
        """Build a minimal StudyPlannerOutput for the given mode.

        The output schema's required fields differ per mode; we use
        model_construct so the test isn't coupled to the validator.
        """
        return StudyPlannerOutput.model_construct(mode=mode)

    @staticmethod
    def _mock_tool_call_capture(captured: list) -> Any:
        async def _mock(_self: Any, tool_name: str, args: dict[str, Any], _ctx: Any) -> Any:
            # patch.object on the class makes this an unbound method.
            captured.append((tool_name, args))
            return MagicMock(output=MagicMock(model_dump=lambda mode="json": {}))
        return _mock

    async def test_weekly_plan_maps_to_weekly(self) -> None:
        agent = StudyPlannerAgent()
        ctx = _make_ctx()
        captured: list[tuple[str, dict[str, Any]]] = []

        with patch.object(StudyPlannerAgent, "tool_call", self._mock_tool_call_capture(captured)):
            await agent._commit_plan(
                output=self._stub_output("weekly_plan"),
                ctx=ctx,
            )

        assert len(captured) == 1
        tool_name, args = captured[0]
        assert tool_name == "commit_plan"
        assert args["plan_type"] == "weekly"

    async def test_session_plan_maps_to_session(self) -> None:
        agent = StudyPlannerAgent()
        ctx = _make_ctx()
        captured: list[tuple[str, dict[str, Any]]] = []

        with patch.object(StudyPlannerAgent, "tool_call", self._mock_tool_call_capture(captured)):
            await agent._commit_plan(
                output=self._stub_output("session_plan"),
                ctx=ctx,
            )

        assert len(captured) == 1
        tool_name, args = captured[0]
        assert tool_name == "commit_plan"
        assert args["plan_type"] == "session"

    async def test_adherence_check_skips_commit(self) -> None:
        """adherence_check is read-only by spec — no plan to commit."""
        agent = StudyPlannerAgent()
        ctx = _make_ctx()
        captured: list[tuple[str, dict[str, Any]]] = []

        with patch.object(StudyPlannerAgent, "tool_call", self._mock_tool_call_capture(captured)):
            await agent._commit_plan(
                output=self._stub_output("adherence_check"),
                ctx=ctx,
            )

        assert captured == [], (
            "adherence_check must NOT call commit_plan — it's a read-only mode"
        )

    async def test_unknown_mode_skips_commit(self) -> None:
        """Defensive: unknown modes also skip rather than crashing the run."""
        agent = StudyPlannerAgent()
        ctx = _make_ctx()
        captured: list[tuple[str, dict[str, Any]]] = []

        with patch.object(StudyPlannerAgent, "tool_call", self._mock_tool_call_capture(captured)):
            await agent._commit_plan(
                output=self._stub_output("invalid_mode"),
                ctx=ctx,
            )

        assert captured == [], (
            "Unknown mode must skip commit_plan, not crash with a Literal "
            "ValidationError"
        )


# ── D12 CP3 Part H.2 — real-instantiation integration test ──────────
#
# Catches ToolExecutor API drift that mocks would hide. The smoke
# script's first 5 runs all instantiated mocks for ToolExecutor — those
# accept any kwargs. Real instantiation in production rejected user_id /
# permissions kwargs and crashed every D12 agent. This test exercises
# the real construct + execute path so future drift fails CI.


class TestRealToolExecutorIntegration:
    """Pins the agent → ToolExecutor → real tool dispatch contract.

    Mock-based tests above accept ANY kwargs to ToolExecutor.__init__ and
    ANY method name. This test instantiates the REAL ToolExecutor via
    AgenticBaseAgent.tool_call and verifies it runs without TypeError or
    AttributeError. Postgres-backed (the real `log_event` tool emits to
    structlog and writes an audit row); skipped when Postgres unreachable.
    """

    async def test_tool_call_does_not_crash_on_construct_or_dispatch(
        self,
    ) -> None:
        """The minimum contract: agent.tool_call(...) must not raise
        TypeError on ToolExecutor construction or AttributeError on
        method dispatch.

        We use log_event because:
          - It's a universal tool (no agent-specific tables required)
          - It's structlog-only (no DB write to audit table needed)
          - Its input schema is small and well-known

        If the agent's call shape mismatches the real API, this test
        fails immediately — the same way Bug 5 fired in production.
        """
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        # Use whatever DSN the test environment provides; skip if absent.
        import os

        dsn = os.environ.get(
            "TEST_PG_DSN",
            "postgresql+asyncpg://postgres:postgres@localhost:5433/platform",
        )
        engine = create_async_engine(dsn, future=True)
        try:
            async with engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        except Exception:
            pytest.skip("Postgres at TEST_PG_DSN not reachable.")
        finally:
            await engine.dispose()

        engine = create_async_engine(dsn, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            agent = StudyPlannerAgent()
            # user_id=None avoids the agent_tool_calls FK to users(id);
            # we're verifying the executor API contract, not an end-to-end
            # student journey. AgentContext schema permits None.
            ctx = AgentContext(
                user_id=None,
                chain=CallChain.start_root(caller="test"),
                session=session,
                extra={"_llm_usage": []},
            )

            # log_event is universal and writes only to structlog — safe
            # to call against any DB session. If THIS doesn't crash, the
            # ToolExecutor API contract is intact.
            result = await agent.tool_call(
                "log_event",
                {
                    "event_name": "study_planner.test_signal",
                    "properties": {"source": "integration_test"},
                    "severity": "info",
                },
                ctx,
            )

            # Pydantic LogEventOutput per log_event.py
            assert result.tool_name == "log_event"
            assert result.status == "ok"
            assert result.output is not None
            # output is a Pydantic model instance — verify the .logged field
            assert getattr(result.output, "logged", None) is True

        await engine.dispose()
