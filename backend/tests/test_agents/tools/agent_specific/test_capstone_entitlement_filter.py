"""D15 CP3 resume / Bug 24 — entitlement + role filter pin tests for the
two pre-existing capstone-read tools.

Both tools previously used `LEFT JOIN exercise_submissions ... LIMIT 1`
without filtering by entitlement; when the calling student had no
submissions, the query fell through to the most-recently-authored
capstone globally. The fix adds:

  - JOIN courses.id via lessons.course_id
  - JOIN course_entitlements (active grants only)
  - LEFT JOIN student_role_state for current_role_id
  - WHERE c.role_id IS NULL OR c.role_id = srs.current_role_id

Six tests total (3 per tool):

  1. Returns NULL when student has zero entitlements.
  2. Returns the in-role capstone when student is entitled to a course
     containing one (Bug 24 happy path).
  3. Does NOT return a cross-role capstone, even when that capstone is
     the most-recently-authored globally (Bug 24 regression guard —
     this is the test that would have caught Bug 24 in CI).

The fixture pattern is the outer-transaction-rollback session from
test_role_state_tools_smoke.py — dev DB seeded data is visible, test
inserts are wiped on teardown.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agents.primitives import communication as comm_mod
from app.agents.tools.agent_specific.career_coach.read_capstone_status import (
    ReadCapstoneStatusInput,
    read_capstone_status,
)
from app.agents.tools.agent_specific.study_planner.read_active_capstone import (
    ReadActiveCapstonesInput,
    read_active_capstone,
)


def _dsn() -> str:
    return os.environ.get(
        "TEST_PG_DSN",
        "postgresql+asyncpg://postgres:postgres@localhost:5433/platform",
    )


def _pg_reachable() -> bool:
    raw = _dsn().replace("postgresql+asyncpg://", "postgresql://", 1)

    async def _probe() -> bool:
        try:
            conn = await asyncpg.connect(raw, timeout=2.0)
            await conn.close()
            return True
        except Exception:
            return False

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


_PG_OK = _pg_reachable()
pytestmark = pytest.mark.skipif(
    not _PG_OK,
    reason="No reachable Postgres at TEST_PG_DSN; skip Bug 24 entitlement tests.",
)


@pytest_asyncio.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_dsn(), echo=False)
    async with engine.connect() as connection:
        outer_tx = await connection.begin()
        async_session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield async_session
        finally:
            await async_session.close()
            await outer_tx.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def session_on_contextvar(
    pg_session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    token = comm_mod._active_session.set(pg_session)
    try:
        yield pg_session
    finally:
        comm_mod._active_session.reset(token)


# ── Helpers ────────────────────────────────────────────────────────────


async def _make_student(
    session: AsyncSession, *, role_slug: str = "python_developer"
) -> uuid.UUID:
    sid = uuid.uuid4()
    await session.execute(
        sql_text(
            "INSERT INTO users (id, email, full_name, hashed_password, "
            "is_active, is_verified, role) "
            "VALUES (:id, :email, :name, 'x', TRUE, FALSE, 'student')"
        ),
        {
            "id": sid,
            "email": f"bug24-{sid}@test.invalid",
            "name": "Bug 24 Test",
        },
    )
    role_id = (
        await session.execute(
            sql_text("SELECT id FROM roles WHERE slug = :s"),
            {"s": role_slug},
        )
    ).scalar_one()
    await session.execute(
        sql_text(
            "INSERT INTO student_role_state "
            "(student_id, current_role_id) "
            "VALUES (:sid, :rid) "
            "ON CONFLICT (student_id) DO UPDATE "
            "SET current_role_id = EXCLUDED.current_role_id"
        ),
        {"sid": sid, "rid": role_id},
    )
    return sid


async def _grant(session: AsyncSession, sid: uuid.UUID, slug: str) -> None:
    cid = (
        await session.execute(
            sql_text("SELECT id FROM courses WHERE slug = :s"),
            {"s": slug},
        )
    ).scalar_one()
    await session.execute(
        sql_text(
            "INSERT INTO course_entitlements "
            "(id, user_id, course_id, source) "
            "VALUES (gen_random_uuid(), :uid, :cid, 'free')"
        ),
        {"uid": sid, "cid": cid},
    )


# ── read_capstone_status (career_coach) ───────────────────────────────


async def test_read_capstone_status_returns_none_for_zero_entitlements(
    session_on_contextvar: AsyncSession,
) -> None:
    """Student has no course entitlement → no capstone visible.

    Pre-Bug-24-fix this returned the most-recent global capstone.
    """
    sid = await _make_student(session_on_contextvar, role_slug="python_developer")

    out = await read_capstone_status(ReadCapstoneStatusInput(student_id=sid))

    assert out.has_capstone is False
    assert out.capstone is None


async def test_read_capstone_status_returns_in_role_capstone(
    session_on_contextvar: AsyncSession,
) -> None:
    """Student entitled to python-foundations (python_developer-tagged)
    sees the python_developer capstone."""
    sid = await _make_student(session_on_contextvar, role_slug="python_developer")
    await _grant(session_on_contextvar, sid, "python-foundations")

    out = await read_capstone_status(ReadCapstoneStatusInput(student_id=sid))

    assert out.has_capstone is True
    assert out.capstone is not None
    # The python-foundations capstone on dev DB is "CLI AI tool".
    assert out.capstone.exercise_title == "CLI AI tool"


async def test_read_capstone_status_does_not_leak_cross_role_capstone(
    session_on_contextvar: AsyncSession,
) -> None:
    """Bug 24 regression guard.

    Student is at python_developer with entitlement to python-foundations
    (in-role) AND intro-ai-engineering (cross-role, genai_engineer-tagged).
    The most-recently-authored capstone globally is the intro-ai-engineering
    one ("D14c CP3 Phase 2: Multi-Agent Eval Harness"). With the fix in
    place, the role filter excludes it; the python_developer capstone
    ("CLI AI tool") is returned instead.
    """
    sid = await _make_student(session_on_contextvar, role_slug="python_developer")
    await _grant(session_on_contextvar, sid, "python-foundations")
    await _grant(session_on_contextvar, sid, "intro-ai-engineering")

    out = await read_capstone_status(ReadCapstoneStatusInput(student_id=sid))

    assert out.has_capstone is True
    assert out.capstone is not None
    # The cross-role capstone must NOT leak through.
    assert "Multi-Agent Eval Harness" not in out.capstone.exercise_title
    assert out.capstone.exercise_title == "CLI AI tool"


# ── read_active_capstone (study_planner) ──────────────────────────────


async def test_read_active_capstone_returns_none_for_zero_entitlements(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar, role_slug="python_developer")

    out = await read_active_capstone(ReadActiveCapstonesInput(student_id=sid))

    assert out.has_active_capstone is False
    assert out.capstone is None


async def test_read_active_capstone_returns_in_role_capstone(
    session_on_contextvar: AsyncSession,
) -> None:
    sid = await _make_student(session_on_contextvar, role_slug="python_developer")
    await _grant(session_on_contextvar, sid, "python-foundations")

    out = await read_active_capstone(ReadActiveCapstonesInput(student_id=sid))

    assert out.has_active_capstone is True
    assert out.capstone is not None
    assert out.capstone.title == "CLI AI tool"


async def test_read_active_capstone_does_not_leak_cross_role_capstone(
    session_on_contextvar: AsyncSession,
) -> None:
    """Bug 24 regression guard for study_planner."""
    sid = await _make_student(session_on_contextvar, role_slug="python_developer")
    await _grant(session_on_contextvar, sid, "python-foundations")
    await _grant(session_on_contextvar, sid, "intro-ai-engineering")

    out = await read_active_capstone(ReadActiveCapstonesInput(student_id=sid))

    assert out.has_active_capstone is True
    assert out.capstone is not None
    assert "Multi-Agent Eval Harness" not in out.capstone.title
    assert out.capstone.title == "CLI AI tool"
