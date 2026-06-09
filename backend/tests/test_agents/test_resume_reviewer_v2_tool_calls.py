"""D12 CP3 Part H.2 — resume_reviewer_v2 real-instantiation integration test.

Same shape as test_career_coach_v2_tool_calls.py — pins the
AgenticBaseAgent.tool_call → real ToolExecutor contract for
resume_reviewer specifically. Catches ToolExecutor API drift.

Postgres-backed; skipped when no Postgres is reachable.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.resume_reviewer_v2 import ResumeReviewerAgent

pytestmark = [pytest.mark.asyncio]


async def test_real_tool_executor_integration() -> None:
    """resume_reviewer.tool_call must NOT crash on construct/dispatch."""
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
        agent = ResumeReviewerAgent()
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
                "event_name": "resume_reviewer.test_signal",
                "properties": {"source": "integration_test"},
                "severity": "info",
            },
            ctx,
        )

        assert result.tool_name == "log_event"
        assert result.status == "ok"
        assert getattr(result.output, "logged", None) is True

    await engine.dispose()
