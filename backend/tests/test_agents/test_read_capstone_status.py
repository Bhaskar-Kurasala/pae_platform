"""D12 CP3 Phase 1 — pin read_capstone_status against real schema.

Bug 8 (sibling of Bug 3): exercise_submissions.submitted_at doesn't
exist; column is created_at. The fixed query orders by es.created_at.

Load-bearing assertion: SQL executes against real Postgres. A
regression that reintroduces `submitted_at` fails at parse time.

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

    schema_name = f"rcs_{uuid.uuid4().hex[:8]}"
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
        # D15 CP3 Bug-24 fix added courses/lessons/entitlements/roles
        # JOINs to read_capstone_status. The throwaway schema mirrors
        # those tables minimally; extended at D15 CP4 closure to cover
        # the full join-graph the post-fix SQL needs.
        await conn.exec_driver_sql(
            """
            CREATE TABLE roles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                slug TEXT UNIQUE NOT NULL,
                sequence_order INT NOT NULL,
                is_terminal BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE courses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                slug VARCHAR(500) NOT NULL,
                role_id UUID NULL REFERENCES roles(id) ON DELETE SET NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE lessons (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE exercises (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                lesson_id UUID NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
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
                feedback TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE course_entitlements (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                course_id UUID NOT NULL REFERENCES courses(id),
                revoked_at TIMESTAMPTZ NULL,
                expires_at TIMESTAMPTZ NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE student_role_state (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id UUID NOT NULL UNIQUE,
                current_role_id UUID NOT NULL REFERENCES roles(id)
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
    from app.agents.tools.agent_specific.career_coach.read_capstone_status import (
        ReadCapstoneStatusInput,
        read_capstone_status,
    )

    token = _active_session.set(session)
    try:
        return await read_capstone_status(
            ReadCapstoneStatusInput(student_id=student_id)
        )
    finally:
        _active_session.reset(token)


async def test_query_executes_against_real_schema_no_data(
    pg_session: AsyncSession,
) -> None:
    """SQL parses against the real schema even with no data.

    Load-bearing: regression to es.submitted_at fails here.
    """
    uid = uuid.uuid4()
    result = await _call_tool(pg_session, uid)
    assert result.has_capstone is False
    assert result.capstone is None


async def _seed_entitled_capstone(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    title: str,
    score: int | None = None,
    feedback: str | None = None,
) -> uuid.UUID:
    """Helper: seed course + lesson + entitlement + capstone exercise
    (and optional submission) so the entitlement-filtered SQL returns
    the row. role_id is NULL on the course so the role-filter clause
    `c.role_id IS NULL OR c.role_id = srs.current_role_id` admits the
    row regardless of whether student_role_state has a row."""
    course_id = uuid.uuid4()
    lesson_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    await session.execute(
        sql_text(
            "INSERT INTO courses (id, slug, role_id) "
            "VALUES (:cid, :slug, NULL)"
        ),
        {"cid": course_id, "slug": f"course-{course_id.hex[:6]}"},
    )
    await session.execute(
        sql_text(
            "INSERT INTO lessons (id, course_id) VALUES (:lid, :cid)"
        ),
        {"lid": lesson_id, "cid": course_id},
    )
    await session.execute(
        sql_text(
            "INSERT INTO exercises (id, lesson_id, title, is_capstone) "
            "VALUES (:eid, :lid, :t, true)"
        ),
        {"eid": exercise_id, "lid": lesson_id, "t": title},
    )
    await session.execute(
        sql_text(
            "INSERT INTO course_entitlements (user_id, course_id) "
            "VALUES (:uid, :cid)"
        ),
        {"uid": student_id, "cid": course_id},
    )
    if score is not None:
        await session.execute(
            sql_text(
                "INSERT INTO exercise_submissions "
                "(student_id, exercise_id, score, feedback) "
                "VALUES (:uid, :eid, :score, :fb)"
            ),
            {
                "uid": student_id,
                "eid": exercise_id,
                "score": score,
                "fb": feedback,
            },
        )
    return exercise_id


async def test_returns_capstone_with_submission(
    pg_session: AsyncSession,
) -> None:
    """End-to-end: capstone + submission seeded; tool returns the row
    ordered by es.created_at DESC NULLS LAST."""
    uid = uuid.uuid4()
    await _seed_entitled_capstone(
        pg_session, student_id=uid, title="Capstone X",
        score=88, feedback="good work",
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert result.has_capstone is True
    assert result.capstone is not None
    assert result.capstone.exercise_title == "Capstone X"
    assert result.capstone.submitted is True
    assert result.capstone.score == 88.0


async def test_unsubmitted_capstone_returned_with_submitted_false(
    pg_session: AsyncSession,
) -> None:
    """A capstone with no submission still shows up; submitted=False.
    NULLS LAST in the ORDER BY ensures unsubmitted capstones aren't
    accidentally hidden."""
    uid = uuid.uuid4()
    await _seed_entitled_capstone(
        pg_session, student_id=uid, title="Unsubmitted Capstone", score=None,
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert result.has_capstone is True
    assert result.capstone is not None
    assert result.capstone.submitted is False
    assert result.capstone.score is None
