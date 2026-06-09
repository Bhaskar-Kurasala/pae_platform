"""Tests for the learning_session_service ordinal + step state machine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.learning_session_service import (
    GAP_MINUTES,
    get_or_open_session,
    mark_step,
    session_count_for_user,
)


async def _make_user(db: AsyncSession, email: str = "ls@test.dev") -> User:
    u = User(email=email, full_name="Learning Tester", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# get_or_open_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_call_opens_session_with_ordinal_one(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    s = await get_or_open_session(db_session, user_id=user.id, now=now)
    assert s.ordinal == 1
    assert s.started_at == now
    assert s.ended_at is None
    assert s.warmup_done_at is None
    assert s.lesson_done_at is None
    assert s.reflect_done_at is None


@pytest.mark.asyncio
async def test_reuses_session_within_gap_minutes(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    t0 = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    first = await get_or_open_session(db_session, user_id=user.id, now=t0)
    # Within the gap window — same row.
    later = t0 + timedelta(minutes=GAP_MINUTES - 1)
    second = await get_or_open_session(db_session, user_id=user.id, now=later)
    assert second.id == first.id
    assert second.ordinal == 1
    assert await session_count_for_user(db_session, user_id=user.id) == 1


@pytest.mark.asyncio
async def test_opens_new_session_after_gap_with_incremented_ordinal(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    t0 = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    first = await get_or_open_session(db_session, user_id=user.id, now=t0)
    later = t0 + timedelta(minutes=GAP_MINUTES + 1)
    second = await get_or_open_session(db_session, user_id=user.id, now=later)
    assert second.id != first.id
    assert second.ordinal == 2
    assert await session_count_for_user(db_session, user_id=user.id) == 2


@pytest.mark.asyncio
async def test_closed_session_forces_new_session_even_inside_gap(
    db_session: AsyncSession,
) -> None:
    """A reflect-closed session must not be re-opened by a fresh fetch."""
    user = await _make_user(db_session)
    t0 = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await mark_step(db_session, user_id=user.id, step="reflect", now=t0)
    # Five minutes later — well inside the gap — but the prior session is
    # closed, so we should get a fresh session at ordinal 2.
    later = t0 + timedelta(minutes=5)
    fresh = await get_or_open_session(db_session, user_id=user.id, now=later)
    assert fresh.ordinal == 2
    assert fresh.ended_at is None


@pytest.mark.asyncio
async def test_session_isolated_per_user(db_session: AsyncSession) -> None:
    a = await _make_user(db_session, "a@ls.test")
    b = await _make_user(db_session, "b@ls.test")
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    sa = await get_or_open_session(db_session, user_id=a.id, now=now)
    sb = await get_or_open_session(db_session, user_id=b.id, now=now)
    assert sa.id != sb.id
    # Both should be ordinal 1 — counters are per-user.
    assert sa.ordinal == 1
    assert sb.ordinal == 1


# ---------------------------------------------------------------------------
# mark_step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_step_warmup_records_timestamp(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    s = await mark_step(db_session, user_id=user.id, step="warmup", now=now)
    assert s.warmup_done_at == now
    assert s.lesson_done_at is None
    assert s.reflect_done_at is None
    assert s.ended_at is None  # warmup does NOT close the session


@pytest.mark.asyncio
async def test_mark_step_lesson_does_not_close_session(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    s = await mark_step(db_session, user_id=user.id, step="lesson", now=now)
    assert s.lesson_done_at == now
    assert s.ended_at is None


@pytest.mark.asyncio
async def test_mark_step_reflect_closes_session(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    s = await mark_step(db_session, user_id=user.id, step="reflect", now=now)
    assert s.reflect_done_at == now
    assert s.ended_at == now


@pytest.mark.asyncio
async def test_mark_step_is_idempotent(db_session: AsyncSession) -> None:
    """Hitting mark_step twice for the same step keeps the original timestamp."""
    user = await _make_user(db_session)
    first_at = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    later = first_at + timedelta(minutes=10)
    s1 = await mark_step(
        db_session, user_id=user.id, step="warmup", now=first_at
    )
    s2 = await mark_step(
        db_session, user_id=user.id, step="warmup", now=later
    )
    assert s1.id == s2.id
    assert s2.warmup_done_at == first_at  # NOT overwritten


@pytest.mark.asyncio
async def test_mark_step_progresses_through_all_three(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    t0 = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await mark_step(db_session, user_id=user.id, step="warmup", now=t0)
    await mark_step(
        db_session,
        user_id=user.id,
        step="lesson",
        now=t0 + timedelta(minutes=20),
    )
    final = await mark_step(
        db_session,
        user_id=user.id,
        step="reflect",
        now=t0 + timedelta(minutes=40),
    )
    assert final.warmup_done_at == t0
    assert final.lesson_done_at == t0 + timedelta(minutes=20)
    assert final.reflect_done_at == t0 + timedelta(minutes=40)
    assert final.ended_at == t0 + timedelta(minutes=40)


# ---------------------------------------------------------------------------
# session_count_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_count_zero_for_unseen_user(
    db_session: AsyncSession,
) -> None:
    assert await session_count_for_user(db_session, user_id=uuid.uuid4()) == 0


@pytest.mark.asyncio
async def test_session_count_grows_with_each_new_session(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    t0 = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    await get_or_open_session(db_session, user_id=user.id, now=t0)
    await get_or_open_session(
        db_session,
        user_id=user.id,
        now=t0 + timedelta(minutes=GAP_MINUTES + 1),
    )
    await get_or_open_session(
        db_session,
        user_id=user.id,
        now=t0 + timedelta(minutes=2 * (GAP_MINUTES + 1)),
    )
    assert await session_count_for_user(db_session, user_id=user.id) == 3
