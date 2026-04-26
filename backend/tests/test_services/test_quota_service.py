"""Quota service tests — first-resume-free + daily/monthly enforcement."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_log import GenerationLog
from app.services.quota_service import (
    DAILY_LIMIT,
    MONTHLY_LIMIT,
    check_quota,
    record_quota_block,
)


def _user_id() -> uuid.UUID:
    return uuid.uuid4()


async def _seed_logs(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    count: int,
    created_at: datetime,
    event: str = "completed",
) -> None:
    for _ in range(count):
        db.add(
            GenerationLog(
                user_id=user_id,
                event=event,
                created_at=created_at,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_first_generation_is_free_when_no_history(db_session: AsyncSession) -> None:
    user = _user_id()
    result = await check_quota(db_session, user_id=user)
    assert result.allowed is True
    assert result.reason == "first_resume_free"


@pytest.mark.asyncio
async def test_first_free_rule_holds_after_only_quota_blocks(db_session: AsyncSession) -> None:
    """Quota-blocked attempts don't count as 'used' — the first paid try still free."""
    user = _user_id()
    now = datetime.now(UTC)
    await _seed_logs(db_session, user, count=3, created_at=now, event="quota_blocked")
    result = await check_quota(db_session, user_id=user, now=now)
    assert result.allowed is True
    assert result.reason == "first_resume_free"


@pytest.mark.asyncio
async def test_within_quota_after_first_generation(db_session: AsyncSession) -> None:
    user = _user_id()
    now = datetime.now(UTC)
    await _seed_logs(db_session, user, count=1, created_at=now)
    result = await check_quota(db_session, user_id=user, now=now)
    assert result.allowed is True
    assert result.reason == "within_quota"
    assert result.remaining_today == DAILY_LIMIT - 1


@pytest.mark.asyncio
async def test_daily_limit_blocks(db_session: AsyncSession) -> None:
    user = _user_id()
    now = datetime.now(UTC)
    await _seed_logs(db_session, user, count=DAILY_LIMIT, created_at=now)
    result = await check_quota(db_session, user_id=user, now=now)
    assert result.allowed is False
    assert result.reason == "daily_limit"
    assert result.remaining_today == 0
    assert result.reset_at is not None
    assert result.reset_at > now


@pytest.mark.asyncio
async def test_monthly_limit_blocks_even_when_today_count_low(db_session: AsyncSession) -> None:
    user = _user_id()
    now = datetime.now(UTC)
    # 20 generations spread over earlier in the month, none today
    earlier = now - timedelta(days=10)
    await _seed_logs(db_session, user, count=MONTHLY_LIMIT, created_at=earlier)
    result = await check_quota(db_session, user_id=user, now=now)
    assert result.allowed is False
    assert result.reason == "monthly_limit"


@pytest.mark.asyncio
async def test_old_generations_outside_window_are_ignored(db_session: AsyncSession) -> None:
    """A returning user from last month should NOT get the first-free rule
    (they've already had a generation in their lifetime), but their old
    monthly count shouldn't block them either.
    """
    user = _user_id()
    now = datetime.now(UTC)
    # User generated their first resume 60 days ago
    long_ago = now - timedelta(days=60)
    await _seed_logs(db_session, user, count=1, created_at=long_ago)
    result = await check_quota(db_session, user_id=user, now=now)
    assert result.allowed is True
    assert result.reason == "within_quota"
    assert result.remaining_today == DAILY_LIMIT
    assert result.remaining_month == MONTHLY_LIMIT


@pytest.mark.asyncio
async def test_record_quota_block_does_not_raise(db_session: AsyncSession) -> None:
    user = _user_id()
    await record_quota_block(db_session, user_id=user, reason="daily_limit")
    # Block events do not consume quota — confirm via check_quota
    now = datetime.now(UTC)
    result = await check_quota(db_session, user_id=user, now=now)
    assert result.reason == "first_resume_free"
