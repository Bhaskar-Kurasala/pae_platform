"""D12 CP3 Phase 1 — pin read_active_capstone against real schema.

Bug 8 (sibling of Bug 3 + read_capstone_status): exercise_submissions
has no submitted_at; column is created_at.

Load-bearing assertion: SQL executes against real schema. Regression
to es.submitted_at fails at parse time.

Postgres-backed; skipped when no Postgres reachable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.agents.primitives.communication import _active_session  # type: ignore[attr-defined]

pytestmark = [pytest.mark.asyncio]

DEFAULT_TEST_DSN = "postgresql+asyncpg://postgres:postgres@localhost:5433/platform"


def _dsn() -> str:
    return os.environ.get("TEST_PG_DSN", DEFAULT_TEST_DSN)


async def _postgres_reachable(dsn: str) -> bool:
    raw = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        conn = await asyncpg.connect(raw, timeout=2.0)
        await conn.close()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="module")
async def _pg_available() -> bool:
    return await _postgres_reachable(_dsn())


@pytest_asyncio.fixture
async def pg_session(_pg_available: bool) -> AsyncGenerator[AsyncSession, None]:
    if not _pg_available:
        pytest.skip("Postgres at TEST_PG_DSN not reachable.")

    schema_name = f"rac_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(
        _dsn(),
        future=True,
        connect_args={
            "server_settings": {"search_path": f"{schema_name},public"},
        },
    )

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'SET search_path TO "{schema_name}", public')
        await conn.exec_driver_sql(
            """
            CREATE TABLE exercises (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title VARCHAR(500) NOT NULL,
                is_capstone BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE exercise_submissions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id UUID NOT NULL,
                exercise_id UUID NOT NULL REFERENCES exercises(id),
                score INT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
            await session.rollback()
        finally:
            pass

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'DROP SCHEMA "{schema_name}" CASCADE')
    await engine.dispose()


async def _call_tool(session: AsyncSession, student_id: uuid.UUID) -> Any:
    from app.agents.tools.agent_specific.study_planner.read_active_capstone import (
        ReadActiveCapstonesInput,
        read_active_capstone,
    )

    token = _active_session.set(session)
    try:
        return await read_active_capstone(
            ReadActiveCapstonesInput(student_id=student_id)
        )
    finally:
        _active_session.reset(token)


async def test_query_executes_against_real_schema_no_data(
    pg_session: AsyncSession,
) -> None:
    """SQL parses against real exercise_submissions schema with no rows.

    Load-bearing: regression to es.submitted_at fails here.
    """
    uid = uuid.uuid4()
    result = await _call_tool(pg_session, uid)
    assert result.has_active_capstone is False
    assert result.capstone is None


async def test_returns_capstone_with_submission(
    pg_session: AsyncSession,
) -> None:
    """End-to-end with seeded data; ORDER BY created_at picks the most
    recent."""
    uid = uuid.uuid4()
    exercise_id = uuid.uuid4()

    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (id, title, is_capstone) "
            "VALUES (:eid, :t, true)"
        ),
        {"eid": exercise_id, "t": "Active Capstone"},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercise_submissions "
            "(student_id, exercise_id, score) VALUES (:uid, :eid, 75)"
        ),
        {"uid": uid, "eid": exercise_id},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert result.has_active_capstone is True
    assert result.capstone is not None
    assert result.capstone.title == "Active Capstone"
    assert result.capstone.submitted is True
    assert result.capstone.score == 75.0
    assert result.capstone.estimated_remaining_hours == 0.0  # submitted → 0 hrs


async def test_unsubmitted_capstone_has_remaining_hours(
    pg_session: AsyncSession,
) -> None:
    """A capstone with no submission shows submitted=False and the
    8-hour estimate."""
    uid = uuid.uuid4()
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (title, is_capstone) "
            "VALUES (:t, true)"
        ),
        {"t": "Unsubmitted"},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert result.has_active_capstone is True
    assert result.capstone is not None
    assert result.capstone.submitted is False
    assert result.capstone.estimated_remaining_hours == 8.0
