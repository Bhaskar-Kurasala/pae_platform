"""D14c CP2 — Phase 1 schema audit (load-bearing) for project_evaluator
net-new tools.

Pins both net-new tools' SQL against the real Postgres schema:
  • read_capstone_submission_content — joins exercise_submissions +
    exercises; verifies columns code, github_pr_url, self_explanation,
    feedback, ai_feedback, score, status, student_id, exercise_id +
    exercises.title, description, is_capstone exist.
  • read_rubric_for_capstone — selects rubric, is_capstone, title from
    exercises; verifies the JSON column reads back as Python dict.

Per D12 Phase 1 audit pattern (see test_read_capstone_status.py): SQL
parses against the real Postgres schema even with no data. A regression
that drifts a column reference fails here at parse time.

Postgres-backed; skipped when no Postgres reachable.
"""

from __future__ import annotations

import json
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

    schema_name = f"pe_{uuid.uuid4().hex[:8]}"
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
        # Mirror the columns in app/models/exercise.py exactly.
        await conn.exec_driver_sql(
            """
            CREATE TABLE exercises (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title VARCHAR(500) NOT NULL,
                description TEXT NULL,
                rubric JSON NULL,
                is_capstone BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Mirror the columns in app/models/exercise_submission.py.
        await conn.exec_driver_sql(
            """
            CREATE TABLE exercise_submissions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id UUID NOT NULL,
                exercise_id UUID NOT NULL REFERENCES exercises(id),
                code TEXT NULL,
                github_pr_url VARCHAR(500) NULL,
                self_explanation TEXT NULL,
                feedback TEXT NULL,
                ai_feedback JSON NULL,
                score INT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                attempt_number INT NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Mirror columns read by read_student_full_progress (it joins
        # courses + lessons + enrollments + student_progress —
        # we don't audit those here since they're D12-pinned).

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


# ── read_capstone_submission_content ───────────────────────────────


async def _call_submission_tool(
    session: AsyncSession, submission_id: uuid.UUID
) -> Any:
    from app.agents.tools.agent_specific.project_evaluator.read_capstone_submission_content import (  # noqa: E501
        ReadCapstoneSubmissionContentInput,
        read_capstone_submission_content,
    )

    token = _active_session.set(session)
    try:
        return await read_capstone_submission_content(
            ReadCapstoneSubmissionContentInput(submission_id=submission_id)
        )
    finally:
        _active_session.reset(token)


async def test_read_capstone_submission_content_query_executes_against_real_schema_no_data(
    pg_session: AsyncSession,
) -> None:
    """SQL parses against the real schema even with no data.

    Load-bearing: any column drift on exercise_submissions or
    exercises (e.g., reintroducing submitted_at) fails here.
    """
    sid = uuid.uuid4()
    result = await _call_submission_tool(pg_session, sid)
    assert result.found is False
    assert result.is_capstone is False
    assert result.code is None


async def test_read_capstone_submission_content_returns_capstone_row(
    pg_session: AsyncSession,
) -> None:
    """End-to-end with seeded data: tool returns the joined row,
    is_capstone=True surfaced at top level (D-4 routing flag)."""
    student_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    submission_id = uuid.uuid4()

    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (id, title, description, is_capstone) "
            "VALUES (:eid, :t, :d, true)"
        ),
        {
            "eid": exercise_id,
            "t": "RAG Capstone",
            "d": "Build a working RAG pipeline.",
        },
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercise_submissions "
            "(id, student_id, exercise_id, code, github_pr_url, "
            "self_explanation, score, status) "
            "VALUES (:sid, :uid, :eid, :code, :pr, :se, 80, 'evaluated')"
        ),
        {
            "sid": submission_id,
            "uid": student_id,
            "eid": exercise_id,
            "code": "def retriever(): pass",
            "pr": "https://github.com/example/pr/42",
            "se": "I built a vector index over docs.",
        },
    )
    await pg_session.flush()

    result = await _call_submission_tool(pg_session, submission_id)
    assert result.found is True
    assert result.is_capstone is True
    assert result.exercise_title == "RAG Capstone"
    assert result.code == "def retriever(): pass"
    assert result.github_pr_url == "https://github.com/example/pr/42"
    assert result.self_explanation == "I built a vector index over docs."
    assert result.score == 80
    assert result.status == "evaluated"
    assert result.student_id == student_id
    assert result.exercise_id == exercise_id


async def test_read_capstone_submission_content_returns_non_capstone_row(
    pg_session: AsyncSession,
) -> None:
    """D-4 routing flag: when exercise.is_capstone=False, tool returns
    found=True with is_capstone=False. Agent's run() owns the
    NON_CAPSTONE_SUBMISSION refusal routing — tool does NOT filter."""
    student_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    submission_id = uuid.uuid4()

    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (id, title, description, is_capstone) "
            "VALUES (:eid, :t, :d, false)"
        ),
        {"eid": exercise_id, "t": "Practice Drill", "d": "Easy warm-up."},
    )
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercise_submissions "
            "(id, student_id, exercise_id, code) "
            "VALUES (:sid, :uid, :eid, :code)"
        ),
        {
            "sid": submission_id,
            "uid": student_id,
            "eid": exercise_id,
            "code": "x = 1",
        },
    )
    await pg_session.flush()

    result = await _call_submission_tool(pg_session, submission_id)
    assert result.found is True
    assert result.is_capstone is False  # the load-bearing D-4 signal


# ── read_rubric_for_capstone ───────────────────────────────────────


async def _call_rubric_tool(
    session: AsyncSession, exercise_id: uuid.UUID
) -> Any:
    from app.agents.tools.agent_specific.project_evaluator.read_rubric_for_capstone import (  # noqa: E501
        ReadRubricForCapstoneInput,
        read_rubric_for_capstone,
    )

    token = _active_session.set(session)
    try:
        return await read_rubric_for_capstone(
            ReadRubricForCapstoneInput(exercise_id=exercise_id)
        )
    finally:
        _active_session.reset(token)


async def test_read_rubric_for_capstone_query_executes_against_real_schema_no_data(
    pg_session: AsyncSession,
) -> None:
    """SQL parses against the real schema even with no data.

    Load-bearing: any column drift on exercises (rubric, is_capstone,
    title) fails here at parse time.
    """
    eid = uuid.uuid4()
    result = await _call_rubric_tool(pg_session, eid)
    assert result.found is False
    assert result.rubric_text is None
    assert result.rubric_json is None


async def test_read_rubric_for_capstone_returns_serialized_text(
    pg_session: AsyncSession,
) -> None:
    """Rubric column read back as dict; tool serializes to
    JSON-pretty rubric_text the prompt consumes verbatim."""
    eid = uuid.uuid4()
    rubric = {
        "architecture": "Does it use RAG appropriately?",
        "code_quality": "Is the code production-ready?",
    }
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (id, title, rubric, is_capstone) "
            "VALUES (:eid, :t, CAST(:r AS JSON), true)"
        ),
        {"eid": eid, "t": "Capstone X", "r": json.dumps(rubric)},
    )
    await pg_session.flush()

    result = await _call_rubric_tool(pg_session, eid)
    assert result.found is True
    assert result.is_capstone is True
    assert result.exercise_title == "Capstone X"
    assert result.rubric_json == rubric
    assert result.rubric_text is not None
    # Pretty-printed (multi-line)
    assert "\n" in result.rubric_text
    # Round-trips
    assert json.loads(result.rubric_text) == rubric


async def test_read_rubric_for_capstone_null_rubric_returns_none(
    pg_session: AsyncSession,
) -> None:
    """D-E rubric-grounding contract: NULL rubric column → rubric_text
    is None; agent will inject RUBRIC_UNAVAILABLE marker into
    user_block."""
    eid = uuid.uuid4()
    await pg_session.execute(
        sql_text(
            "INSERT INTO exercises (id, title, is_capstone) "
            "VALUES (:eid, :t, true)"
        ),
        {"eid": eid, "t": "Capstone Y"},
    )
    await pg_session.flush()

    result = await _call_rubric_tool(pg_session, eid)
    assert result.found is True
    assert result.is_capstone is True
    assert result.rubric_json is None
    assert result.rubric_text is None
