"""D12 CP3 Part H.2 — career_coach_v2 real-instantiation integration test.

Catches ToolExecutor API drift that mocks would hide. CP2 wrote
career_coach_v2 with the wrong ToolExecutor constructor kwargs and a
non-existent .call() method. Mock-based unit tests accepted any shape
silently. This test instantiates the REAL ToolExecutor via
AgenticBaseAgent.tool_call to pin the contract.

Postgres-backed; skipped when no Postgres is reachable.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.career_coach_v2 import CareerCoachAgent

pytestmark = [pytest.mark.asyncio]


async def test_real_tool_executor_integration() -> None:
    """career_coach.tool_call must NOT raise TypeError on construction
    or AttributeError on dispatch. Bug 5 made every CP2 agent crash here.
    """
    dsn = os.environ.get(
        "TEST_PG_DSN",
        "postgresql+asyncpg://postgres:postgres@localhost:5433/platform",
    )
    engine = create_async_engine(dsn, future=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(sql_text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres at TEST_PG_DSN not reachable.")
    finally:
        await engine.dispose()

    engine = create_async_engine(dsn, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        agent = CareerCoachAgent()
        # user_id=None avoids the agent_tool_calls FK to users(id).
        ctx = AgentContext(
            user_id=None,
            chain=CallChain.start_root(caller="test"),
            session=session,
            extra={"_llm_usage": []},
        )

        result = await agent.tool_call(
            "log_event",
            {
                "event_name": "career_coach.test_signal",
                "properties": {"source": "integration_test"},
                "severity": "info",
            },
            ctx,
        )

        assert result.tool_name == "log_event"
        assert result.status == "ok"
        assert getattr(result.output, "logged", None) is True

    await engine.dispose()
