"""D12 CP3 Part G — pin read_capstones column reference.

The CP2-shipped read_capstones.py used `ORDER BY es.submitted_at DESC`,
but exercise_submissions has no submitted_at column (only created_at
from TimestampMixin). The query parsed to UndefinedColumnError; the
broad except swallowed it; resume_reviewer received capstones=[] and
its grounded-evidence promise became vacuous.

This test pins the corrected column reference (created_at) so a
future regression to submitted_at fails CI.

Postgres-backed (the column existence check uses real DDL); skipped
when no Postgres reachable.
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

    schema_name = f"capstone_filter_{uuid.uuid4().hex[:8]}"
    base_dsn = _dsn()
    engine = create_async_engine(
        base_dsn,
        future=True,
        connect_args={
            "server_settings": {"search_path": f"{schema_name},public"},
        },
    )

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')

    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            f'SET search_path TO "{schema_name}", public'
        )
        # Real columns matching exercise_submissions (no submitted_at).
        await conn.exec_driver_sql(
            """
            CREATE TABLE exercises (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title VARCHAR(255) NOT NULL,
                is_capstone BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
                feedback TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
    from app.agents.tools.agent_specific.resume_reviewer.read_capstones import (
        ReadCapstonesInput,
        read_capstones,
    )

    token = _active_session.set(session)
    try:
        return await read_capstones(ReadCapstonesInput(student_id=student_id))
    finally:
        _active_session.reset(token)


async def test_read_capstones_returns_seeded_submission(
    pg_session: AsyncSession,
) -> None:
    """A seeded capstone submission is returned by the tool.

    Pins the corrected column reference: ORDER BY created_at (was
    submitted_at — never existed). If a future regression flips back
    to submitted_at, this test fails with UndefinedColumnError → tool
    returns total=0 → assert blows up loudly.
    """
    uid = uuid.uuid4()
    exercise_id = uuid.uuid4()

    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (id, title, is_capstone) "
            "VALUES (:eid, :title, true)"
        ),
        {"eid": exercise_id, "title": "Test capstone"},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercise_submissions "
            "(student_id, exercise_id, score, feedback) "
            "VALUES (:uid, :eid, 92, 'great work on RAG')"
        ),
        {"uid": uid, "eid": exercise_id},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert result.total == 1, (
        "Expected 1 capstone — read_capstones SQL must reference "
        "real columns. If total=0, the tool's broad except swallowed "
        "an UndefinedColumnError (likely submitted_at vs created_at)."
    )
    assert len(result.capstones) == 1
    assert result.capstones[0].title == "Test capstone"
    assert result.capstones[0].score == 92.0
    assert result.capstones[0].feedback_snippet is not None
    assert "rag" in result.capstones[0].feedback_snippet.lower()


async def test_read_capstones_filters_non_capstone(
    pg_session: AsyncSession,
) -> None:
    """Non-capstone exercises must NOT appear in the result."""
    uid = uuid.uuid4()
    cap_id = uuid.uuid4()
    non_cap_id = uuid.uuid4()

    await pg_session.execute(
        sql_text("INSERT INTO exercises (id, title, is_capstone) VALUES (:id, 'cap', true)"),
        {"id": cap_id},
    )
    await pg_session.execute(
        sql_text("INSERT INTO exercises (id, title, is_capstone) VALUES (:id, 'non-cap', false)"),
        {"id": non_cap_id},
    )
    await pg_session.execute(
        sql_text("INSERT INTO exercise_submissions (student_id, exercise_id, score) VALUES (:uid, :eid, 80)"),
        {"uid": uid, "eid": cap_id},
    )
    await pg_session.execute(
        sql_text("INSERT INTO exercise_submissions (student_id, exercise_id, score) VALUES (:uid, :eid, 70)"),
        {"uid": uid, "eid": non_cap_id},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert result.total == 1
    assert result.capstones[0].title == "cap"
