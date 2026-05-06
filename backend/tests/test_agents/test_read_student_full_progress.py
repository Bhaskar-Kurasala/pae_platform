"""D12 CP3 Phase 1 — pin read_student_full_progress against real schema.

Two CP2 column-reference bugs, both caught in the Phase 1 audit:
  Bug 9: ex.course_id alias is invalid; exercises link to lessons,
         not courses. Routed via lessons.course_id.
  Bug 12: student_progress.completed doesn't exist. The completion
         signal is completed_at IS NOT NULL.

The load-bearing assertion is "the SQL executes against real Postgres"
— a future regression that reintroduces either column reference fails
the test at parse time with UndefinedColumnError, even before the
result-shape assertions run.

Postgres-backed; skipped when no Postgres is reachable.
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

    schema_name = f"rsfp_{uuid.uuid4().hex[:8]}"
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
        # Schemas mirror migrations 0001/0002/etc — only the columns the
        # query actually touches.
        await conn.exec_driver_sql(
            """
            CREATE TABLE courses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title VARCHAR(500) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE lessons (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                course_id UUID NOT NULL REFERENCES courses(id),
                title VARCHAR(500) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE enrollments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id UUID NOT NULL,
                course_id UUID NOT NULL REFERENCES courses(id),
                progress_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE student_progress (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id UUID NOT NULL,
                lesson_id UUID NOT NULL REFERENCES lessons(id),
                status VARCHAR(50) NOT NULL DEFAULT 'not_started',
                completed_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE exercises (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                lesson_id UUID NOT NULL REFERENCES lessons(id),
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
    from app.agents.tools.agent_specific.career_coach.read_student_full_progress import (
        ReadStudentFullProgressInput,
        read_student_full_progress,
    )

    token = _active_session.set(session)
    try:
        return await read_student_full_progress(
            ReadStudentFullProgressInput(student_id=student_id)
        )
    finally:
        _active_session.reset(token)


async def test_query_executes_against_real_schema_no_data(
    pg_session: AsyncSession,
) -> None:
    """The SQL must parse cleanly even with zero seeded data.

    This is the load-bearing assertion: a regression that reintroduces
    `sp.completed` or `ex.course_id` fails here at parse time with
    UndefinedColumnError. The result-shape assertions are secondary.
    """
    uid = uuid.uuid4()
    result = await _call_tool(pg_session, uid)

    # SQL executed cleanly (no UndefinedColumnError).
    assert result is not None
    assert result.courses == []
    assert result.total_lessons_completed == 0


async def test_returns_seeded_progress(pg_session: AsyncSession) -> None:
    """End-to-end: seeded enrollment + completed lesson + scored submission
    flows through the corrected query. Asserts the lessons-via-exercises
    join and the completed_at filter both work."""
    uid = uuid.uuid4()
    course_id = uuid.uuid4()
    lesson_id = uuid.uuid4()
    exercise_id = uuid.uuid4()

    await pg_session.execute(
        sql_text("INSERT INTO courses (id, title) VALUES (:cid, :title)"),
        {"cid": course_id, "title": "Test Course"},
    )
    await pg_session.execute(
        sql_text("INSERT INTO lessons (id, course_id, title) VALUES (:lid, :cid, :t)"),
        {"lid": lesson_id, "cid": course_id, "t": "Lesson 1"},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO enrollments (student_id, course_id, progress_pct) "
            "VALUES (:uid, :cid, :pct)"
        ),
        {"uid": uid, "cid": course_id, "pct": 50.0},
    )
    # One completed (completed_at set), one in-progress (completed_at NULL)
    # — query should count exactly one completed.
    await pg_session.execute(
        sql_text(
            "INSERT INTO student_progress (student_id, lesson_id, status, completed_at) "
            "VALUES (:uid, :lid, 'completed', now())"
        ),
        {"uid": uid, "lid": lesson_id},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (id, lesson_id, title) VALUES (:eid, :lid, :t)"
        ),
        {"eid": exercise_id, "lid": lesson_id, "t": "Ex1"},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercise_submissions (student_id, exercise_id, score) "
            "VALUES (:uid, :eid, :s)"
        ),
        {"uid": uid, "eid": exercise_id, "s": 90},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)

    assert len(result.courses) == 1
    cp = result.courses[0]
    assert cp.course_title == "Test Course"
    assert cp.completion_pct == 50.0
    assert cp.lessons_completed == 1, (
        "completed_at IS NOT NULL filter must pick up the seeded row"
    )
    assert cp.avg_exercise_score == 90.0


async def test_per_course_aggregation_does_not_cross_courses(
    pg_session: AsyncSession,
) -> None:
    """Bug 13 regression pin: avg_exercise_score is per-course, not student-global.

    Pre-fix, the broken `LEFT JOIN exercise_submissions es ON es.student_id = e.student_id`
    joined submissions only by student — so every course row aggregated
    EVERY submission the student ever made (across all courses). Career
    coach saw the student's global average attributed to each enrolled
    course. Strategic recommendations downstream were based on broken
    aggregation.

    The fix routes exercises through lessons (`ex.lesson_id = l.id`)
    AND tightens the submissions join to that exercises chain (`es.exercise_id = ex.id`).
    This test seeds two courses for one student with very different
    submission scores and asserts each course's avg_exercise_score
    reflects only that course's own submissions.
    """
    uid = uuid.uuid4()
    # Course A — 1 exercise, score 100
    course_a = uuid.uuid4()
    lesson_a = uuid.uuid4()
    ex_a = uuid.uuid4()
    # Course B — 1 exercise, score 40
    course_b = uuid.uuid4()
    lesson_b = uuid.uuid4()
    ex_b = uuid.uuid4()

    await pg_session.execute(
        sql_text("INSERT INTO courses (id, title) VALUES (:cid, 'A High')"),
        {"cid": course_a},
    )
    await pg_session.execute(
        sql_text("INSERT INTO courses (id, title) VALUES (:cid, 'B Low')"),
        {"cid": course_b},
    )
    await pg_session.execute(
        sql_text("INSERT INTO lessons (id, course_id, title) VALUES (:lid, :cid, 'L')"),
        {"lid": lesson_a, "cid": course_a},
    )
    await pg_session.execute(
        sql_text("INSERT INTO lessons (id, course_id, title) VALUES (:lid, :cid, 'L')"),
        {"lid": lesson_b, "cid": course_b},
    )
    await pg_session.execute(
        sql_text("INSERT INTO enrollments (student_id, course_id) VALUES (:uid, :cid)"),
        {"uid": uid, "cid": course_a},
    )
    await pg_session.execute(
        sql_text("INSERT INTO enrollments (student_id, course_id) VALUES (:uid, :cid)"),
        {"uid": uid, "cid": course_b},
    )
    await pg_session.execute(
        sql_text("INSERT INTO exercises (id, lesson_id, title) VALUES (:eid, :lid, 'E')"),
        {"eid": ex_a, "lid": lesson_a},
    )
    await pg_session.execute(
        sql_text("INSERT INTO exercises (id, lesson_id, title) VALUES (:eid, :lid, 'E')"),
        {"eid": ex_b, "lid": lesson_b},
    )
    # Score 100 in course A, score 40 in course B.
    # Pre-fix would have averaged BOTH submissions into BOTH courses → 70 each.
    # Post-fix: course A=100, course B=40.
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercise_submissions (student_id, exercise_id, score) "
            "VALUES (:uid, :eid, 100)"
        ),
        {"uid": uid, "eid": ex_a},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercise_submissions (student_id, exercise_id, score) "
            "VALUES (:uid, :eid, 40)"
        ),
        {"uid": uid, "eid": ex_b},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert len(result.courses) == 2
    by_title = {c.course_title: c for c in result.courses}
    assert "A High" in by_title and "B Low" in by_title

    # The point: 100 must NOT show up under B Low, and 40 must NOT show
    # up under A High. The pre-fix broken join would have made both
    # courses report the global average (70).
    assert by_title["A High"].avg_exercise_score == 100.0, (
        "Course A's avg should reflect ONLY its own exercise (score 100). "
        "If this returns 70, the cartesian-style join (Bug 13) regressed."
    )
    assert by_title["B Low"].avg_exercise_score == 40.0, (
        "Course B's avg should reflect ONLY its own exercise (score 40). "
        "If this returns 70, the cartesian-style join (Bug 13) regressed."
    )


async def test_in_progress_lesson_not_counted_as_completed(
    pg_session: AsyncSession,
) -> None:
    """A student_progress row with completed_at=NULL must NOT be counted.

    Pins the Bug 12 fix: switching from `WHERE sp.completed` (column
    that doesn't exist) to `WHERE sp.completed_at IS NOT NULL` doesn't
    accidentally count in-progress rows.
    """
    uid = uuid.uuid4()
    course_id = uuid.uuid4()
    lesson_id = uuid.uuid4()

    await pg_session.execute(
        sql_text("INSERT INTO courses (id, title) VALUES (:cid, :t)"),
        {"cid": course_id, "t": "T"},
    )
    await pg_session.execute(
        sql_text("INSERT INTO lessons (id, course_id, title) VALUES (:lid, :cid, :t)"),
        {"lid": lesson_id, "cid": course_id, "t": "L"},
    )
    await pg_session.execute(
        sql_text("INSERT INTO enrollments (student_id, course_id) VALUES (:uid, :cid)"),
        {"uid": uid, "cid": course_id},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO student_progress (student_id, lesson_id, status, completed_at) "
            "VALUES (:uid, :lid, 'in_progress', NULL)"
        ),
        {"uid": uid, "lid": lesson_id},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert len(result.courses) == 1
    assert result.courses[0].lessons_completed == 0
