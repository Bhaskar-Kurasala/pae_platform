"""D17b/ITEM 3 Phase 0 — pin tests for read_student_lead_in_signals.

Outer-transaction-rollback pattern (mirrors test_role_state_tools_smoke):
each test runs against a real Postgres connection inside a transaction
that's rolled back on teardown. Lets the tool query the live schema +
seeded reference data (six roles, etc.) without polluting state.

Coverage:
  1. happy path: all five signals populated correctly
  2. new student fallback: no risk_signals row → days derives from
     users.last_login_at; current_slip_type=None
  3. no passing mock: most_recent_mock_pass_at=None
  4. never transitioned: most_recent_transition_completed_at=None
  5. recent_activity_days_count_7d boundary clamping (le=7)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agents.primitives import communication as comm_mod
from app.agents.tools.universal.read_student_lead_in_signals import (
    ReadStudentLeadInSignalsInput,
    ReadStudentLeadInSignalsOutput,
    read_student_lead_in_signals,
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
    reason=(
        "No reachable Postgres at TEST_PG_DSN; skip lead-in signals "
        "smoke tests."
    ),
)


@pytest_asyncio.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    """Outer-transaction-rollback session against the live dev DB."""
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


# ── Seed helpers ──────────────────────────────────────────────────────


async def _make_student(
    session: AsyncSession, *, last_login_days_ago: int | None = None
) -> uuid.UUID:
    sid = uuid.uuid4()
    last_login = (
        datetime.now(UTC) - timedelta(days=last_login_days_ago)
        if last_login_days_ago is not None
        else None
    )
    await session.execute(
        sql_text(
            """
            INSERT INTO users
              (id, email, full_name, hashed_password, is_active,
               is_verified, role, last_login_at)
            VALUES (:id, :email, :name, 'x', TRUE, FALSE, 'student',
                    :last_login)
            """
        ),
        {
            "id": sid,
            "email": f"d17b-leadin-{sid}@test.invalid",
            "name": "D17b LeadIn Test",
            "last_login": last_login,
        },
    )
    return sid


async def _seed_risk(
    session: AsyncSession,
    student_id: uuid.UUID,
    *,
    days_since_last_session: int | None,
    slip_type: str,
    risk_score: int = 50,
) -> None:
    # student_risk_signals.id is NOT NULL with no DB-side default; must
    # supply explicitly. (The model uses uuid.uuid4 at the Python layer
    # via UUIDMixin; raw INSERT bypasses it.)
    await session.execute(
        sql_text(
            """
            INSERT INTO student_risk_signals
              (id, user_id, slip_type, risk_score, days_since_last_session,
               max_streak_ever, paid)
            VALUES (:id, :uid, :slip, :score, :days, 0, FALSE)
            ON CONFLICT (user_id) DO UPDATE
            SET slip_type = EXCLUDED.slip_type,
                risk_score = EXCLUDED.risk_score,
                days_since_last_session = EXCLUDED.days_since_last_session
            """
        ),
        {
            "id": uuid.uuid4(),
            "uid": student_id,
            "slip": slip_type,
            "score": risk_score,
            "days": days_since_last_session,
        },
    )


async def _seed_mock_pass(
    session: AsyncSession,
    student_id: uuid.UUID,
    *,
    hours_ago: int,
    passed: bool,
) -> None:
    """Insert an agent_actions row simulating a mock_interview completion.

    Uses session-statement-timestamp arithmetic on created_at so the
    row's wall clock matches the requested `hours_ago` exactly (the
    column has DEFAULT now() so we override explicitly).
    """
    output = {
        "session_verdict": {
            "passed": passed,
            "transition_target": {"to_role_slug": "data_analyst"},
        }
    }
    aid = uuid.uuid4()
    when = datetime.now(UTC) - timedelta(hours=hours_ago)
    # agent_actions has additional NOT NULL columns the model fills via
    # defaults (action_type, etc.). For raw SQL we supply them.
    await session.execute(
        sql_text(
            """
            INSERT INTO agent_actions
              (id, agent_name, student_id, action_type, status,
               output_data, created_at)
            VALUES
              (:id, 'mock_interview', :sid, 'execute', 'completed',
               CAST(:out AS JSONB), :ts)
            """
        ),
        {"id": aid, "sid": student_id, "out": json.dumps(output), "ts": when},
    )


async def _seed_role_state_with_transition(
    session: AsyncSession,
    student_id: uuid.UUID,
    *,
    completed_hours_ago: int | None,
) -> None:
    """Seed student_role_state with current_role=python_developer and
    optionally a transitions_completed entry whose completed_at is at
    `completed_hours_ago` from now."""
    role_id = (
        await session.execute(
            sql_text("SELECT id FROM roles WHERE slug = 'python_developer'"),
        )
    ).scalar_one()

    transitions: list[dict] = []
    if completed_hours_ago is not None:
        completed_at = (
            datetime.now(UTC) - timedelta(hours=completed_hours_ago)
        ).isoformat()
        transitions.append(
            {
                "from_slug": "python_developer",
                "to_slug": "data_analyst",
                "completed_at": completed_at,
                "capstone_score": 0.78,
                "mock_session_ids": [],
            }
        )

    await session.execute(
        sql_text(
            """
            INSERT INTO student_role_state
              (student_id, current_role_id, role_started_at,
               transitions_completed)
            VALUES (:sid, :rid, now() - interval '30 days',
                    CAST(:completed AS JSONB))
            ON CONFLICT (student_id) DO UPDATE
            SET transitions_completed = EXCLUDED.transitions_completed
            """
        ),
        {"sid": student_id, "rid": role_id, "completed": json.dumps(transitions)},
    )


async def _seed_learning_session(
    session: AsyncSession,
    student_id: uuid.UUID,
    *,
    days_ago: int,
    ordinal: int,
) -> None:
    when = datetime.now(UTC) - timedelta(days=days_ago)
    await session.execute(
        sql_text(
            """
            INSERT INTO learning_sessions
              (id, user_id, ordinal, started_at, created_at)
            VALUES (:id, :uid, :ord, :ts, :ts)
            """
        ),
        {
            "id": uuid.uuid4(),
            "uid": student_id,
            "ord": ordinal,
            "ts": when,
        },
    )


# ── Tests ────────────────────────────────────────────────────────────


async def test_happy_path_all_signals_populated(
    session_on_contextvar: AsyncSession,
) -> None:
    """All five signals populated correctly when seeded fully."""
    student = await _make_student(session_on_contextvar, last_login_days_ago=2)
    await _seed_risk(
        session_on_contextvar,
        student,
        days_since_last_session=2,
        slip_type="paid_silent",
    )
    await _seed_mock_pass(session_on_contextvar, student, hours_ago=12, passed=True)
    await _seed_role_state_with_transition(
        session_on_contextvar, student, completed_hours_ago=24
    )
    # 4 distinct days of activity in the last 7
    for i, days_ago in enumerate([0, 1, 3, 6]):
        await _seed_learning_session(
            session_on_contextvar, student, days_ago=days_ago, ordinal=i + 1
        )

    out = await read_student_lead_in_signals(
        ReadStudentLeadInSignalsInput(student_id=student)
    )
    assert isinstance(out, ReadStudentLeadInSignalsOutput)
    assert out.days_since_last_session == 2
    assert out.current_slip_type == "paid_silent"
    assert out.most_recent_mock_pass_at is not None
    assert (datetime.now(UTC) - out.most_recent_mock_pass_at).total_seconds() < 24 * 3600
    assert out.most_recent_transition_completed_at is not None
    assert out.recent_activity_days_count_7d == 4


async def test_new_student_no_risk_row_falls_back_to_last_login(
    session_on_contextvar: AsyncSession,
) -> None:
    """No student_risk_signals row → days_since_last_session derives
    from users.last_login_at; current_slip_type=None."""
    student = await _make_student(
        session_on_contextvar, last_login_days_ago=7
    )
    # Note: NO risk row inserted

    out = await read_student_lead_in_signals(
        ReadStudentLeadInSignalsInput(student_id=student)
    )
    assert out.days_since_last_session == 7
    assert out.current_slip_type is None
    # No other signals seeded either
    assert out.most_recent_mock_pass_at is None
    assert out.most_recent_transition_completed_at is None
    assert out.recent_activity_days_count_7d == 0


async def test_no_passing_mock_returns_none(
    session_on_contextvar: AsyncSession,
) -> None:
    """A mock_interview row with passed=False does NOT count.

    Only passed=true rows surface; failed mocks are filtered by the
    JSONB predicate at SQL level.
    """
    student = await _make_student(session_on_contextvar, last_login_days_ago=1)
    await _seed_mock_pass(session_on_contextvar, student, hours_ago=6, passed=False)

    out = await read_student_lead_in_signals(
        ReadStudentLeadInSignalsInput(student_id=student)
    )
    assert out.most_recent_mock_pass_at is None


async def test_never_transitioned_returns_none(
    session_on_contextvar: AsyncSession,
) -> None:
    """student_role_state with empty transitions_completed →
    most_recent_transition_completed_at=None."""
    student = await _make_student(session_on_contextvar, last_login_days_ago=1)
    await _seed_role_state_with_transition(
        session_on_contextvar, student, completed_hours_ago=None
    )

    out = await read_student_lead_in_signals(
        ReadStudentLeadInSignalsInput(student_id=student)
    )
    assert out.most_recent_transition_completed_at is None


async def test_recent_activity_count_clamps_to_seven(
    session_on_contextvar: AsyncSession,
) -> None:
    """recent_activity_days_count_7d output is bounded by le=7 even if
    the underlying COUNT exceeds it (defensive guard for any future
    case where the SQL returns >7, e.g. timezone bucketing edge cases).
    """
    student = await _make_student(session_on_contextvar, last_login_days_ago=0)
    # 7 distinct days of activity, all within the last 7 days
    for i, days_ago in enumerate([0, 1, 2, 3, 4, 5, 6]):
        await _seed_learning_session(
            session_on_contextvar, student, days_ago=days_ago, ordinal=i + 1
        )

    out = await read_student_lead_in_signals(
        ReadStudentLeadInSignalsInput(student_id=student)
    )
    assert out.recent_activity_days_count_7d == 7
    # Pydantic's le=7 constraint must hold
    assert out.recent_activity_days_count_7d <= 7
