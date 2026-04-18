"""Unit tests for the weekly-letter delivery helper (P1-C-4).

We mock the LLM call inside `_compose_letter` so tests don't hit Anthropic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.growth_snapshot import GrowthSnapshot
from app.models.notification import Notification
from app.models.user import User
from app.services.email_service import EmailService
from app.tasks.weekly_letters import NOTIFICATION_TYPE, _already_sent


async def _make_user(db: AsyncSession) -> User:
    u = User(email="letter@test.dev", full_name="Letter Test", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_snapshot(db: AsyncSession, user_id: uuid.UUID) -> GrowthSnapshot:
    snap = GrowthSnapshot(
        user_id=user_id,
        week_ending=date(2026, 4, 12),
        lessons_completed=3,
        skills_touched=4,
        streak_days=5,
        top_concept="Attention",
        payload={"quiz_attempts": 2, "quiz_avg_score": 0.8, "reflections": 1},
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap


@pytest.mark.asyncio
async def test_already_sent_returns_false_when_no_notifications(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    assert await _already_sent(db_session, user.id, "2026-04-12") is False


@pytest.mark.asyncio
async def test_already_sent_returns_true_when_week_matches(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    db_session.add(
        Notification(
            user_id=user.id,
            title="prior",
            body="prior",
            notification_type=NOTIFICATION_TYPE,
            metadata_={"week_ending": "2026-04-12"},
        )
    )
    await db_session.commit()

    assert await _already_sent(db_session, user.id, "2026-04-12") is True
    # Different week — should return False.
    assert await _already_sent(db_session, user.id, "2026-04-05") is False


@pytest.mark.asyncio
async def test_already_sent_ignores_other_notification_types(
    db_session: AsyncSession,
) -> None:
    """A non-weekly_letter notification for the same week must NOT be treated as sent."""
    user = await _make_user(db_session)
    db_session.add(
        Notification(
            user_id=user.id,
            title="unrelated",
            body="unrelated",
            notification_type="enrollment",
            metadata_={"week_ending": "2026-04-12"},
        )
    )
    await db_session.commit()

    assert await _already_sent(db_session, user.id, "2026-04-12") is False
