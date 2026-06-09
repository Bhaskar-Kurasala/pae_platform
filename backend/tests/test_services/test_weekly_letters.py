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
from app.models.outreach_log import OutreachLog
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
async def test_deliver_letter_writes_outreach_log_row_on_email_success(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D16/CP2.i — successful weekly_letter email writes an outreach_log row.

    Closes the audit-log gap where weekly_letter sends bypassed
    outreach_service.record() and were therefore invisible in the per-
    student outreach feed on the admin cockpit.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.tasks import weekly_letters as wl

    # Fresh user + snapshot in the per-test schema.
    user = await _make_user(db_session)
    snap = await _make_snapshot(db_session, user.id)

    # Bind the helper's `async with AsyncSessionLocal()` to the per-test
    # schema so notification + outreach_log writes land here.
    test_session_factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False
    )
    monkeypatch.setattr(
        "app.tasks.weekly_letters.AsyncSessionLocal",
        test_session_factory,
        raising=False,
    )

    # Mock the LLM so we don't hit Anthropic; mock email send to True.
    monkeypatch.setattr(
        "app.tasks.weekly_letters._compose_letter",
        AsyncMock(return_value="A short personal weekly note. Keep going!"),
    )
    email_service = EmailService()
    monkeypatch.setattr(
        email_service,
        "send_weekly_letter",
        AsyncMock(return_value=True),
    )

    result = await wl._deliver_letter(user, snap, email_service)

    assert result == {"notification": True, "email": True}

    # Assert exactly one outreach_log row landed with the expected shape.
    rows = (
        await db_session.execute(
            select(OutreachLog).where(OutreachLog.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.channel == "email"
    assert row.template_key == "weekly_letter"
    assert row.triggered_by == "system_weekly_letters"
    assert row.status == "sent"
    assert row.body_preview is not None
    assert row.body_preview.startswith("A short personal weekly note")


@pytest.mark.asyncio
async def test_deliver_letter_skips_outreach_log_when_email_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When SendGrid call returns False (no API key, mocked), no outreach_log row.

    The audit trail is only the structlog `weekly_letter.email_failed`
    line in that case; we don't want spurious 'sent' rows for emails
    that didn't actually go out.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.tasks import weekly_letters as wl

    user = await _make_user(db_session)
    snap = await _make_snapshot(db_session, user.id)

    test_session_factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False
    )
    monkeypatch.setattr(
        "app.tasks.weekly_letters.AsyncSessionLocal",
        test_session_factory,
        raising=False,
    )

    monkeypatch.setattr(
        "app.tasks.weekly_letters._compose_letter",
        AsyncMock(return_value="A short personal weekly note."),
    )
    email_service = EmailService()
    monkeypatch.setattr(
        email_service,
        "send_weekly_letter",
        AsyncMock(return_value=False),
    )

    result = await wl._deliver_letter(user, snap, email_service)
    assert result == {"notification": True, "email": False}

    rows = (
        await db_session.execute(
            select(OutreachLog).where(OutreachLog.user_id == user.id)
        )
    ).scalars().all()
    assert rows == []


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
