"""F3 — OutreachService tests.

Six tests covering the contract:
  - record persists a row with all fields
  - was_sent_recently returns True within window
  - was_sent_recently returns False outside window
  - was_sent_recently is keyed per template (different templates don't
    block each other)
  - mark_delivered / mark_opened are idempotent
  - failed status doesn't block retry (was_sent_recently excludes it)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog
from app.models.user import User
from app.services import outreach_service


async def _make_user(db: AsyncSession) -> User:
    """Minimal user for FK referential integrity."""
    user = User(
        id=uuid.uuid4(),
        email=f"u{uuid.uuid4().hex[:8]}@test.dev",
        full_name="Test User",
        hashed_password="x",
        role="student",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_record_persists_all_fields(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    entry = await outreach_service.record(
        db_session,
        user_id=user.id,
        channel="email",
        template_key="paid_silent_day_3",
        slip_type="paid_silent",
        triggered_by="system_nightly",
        body_preview="Hi Test, I noticed you paid…",
        status="sent",
    )
    assert entry.id is not None
    assert entry.user_id == user.id
    assert entry.channel == "email"
    assert entry.template_key == "paid_silent_day_3"
    assert entry.slip_type == "paid_silent"
    assert entry.triggered_by == "system_nightly"
    assert entry.body_preview == "Hi Test, I noticed you paid…"
    assert entry.status == "sent"


@pytest.mark.asyncio
async def test_was_sent_recently_within_window(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await outreach_service.record(
        db_session,
        user_id=user.id,
        channel="email",
        template_key="cold_signup_day_1",
        slip_type="cold_signup",
        triggered_by="system_nightly",
        status="sent",
    )
    # Within default 7-day window — should be blocked.
    assert (
        await outreach_service.was_sent_recently(
            db_session, user_id=user.id, template_key="cold_signup_day_1"
        )
        is True
    )


@pytest.mark.asyncio
async def test_was_sent_recently_outside_window(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    # Manually insert a row dated 30 days ago.
    old = OutreachLog(
        id=uuid.uuid4(),
        user_id=user.id,
        channel="email",
        template_key="cold_signup_day_1",
        slip_type="cold_signup",
        triggered_by="system_nightly",
        sent_at=datetime.now(UTC) - timedelta(days=30),
        status="sent",
    )
    db_session.add(old)
    await db_session.commit()

    assert (
        await outreach_service.was_sent_recently(
            db_session,
            user_id=user.id,
            template_key="cold_signup_day_1",
            within_days=7,
        )
        is False
    )


@pytest.mark.asyncio
async def test_throttle_is_per_template(db_session: AsyncSession) -> None:
    """Sending day_1 doesn't block day_3 — they're separate cadence steps."""
    user = await _make_user(db_session)
    await outreach_service.record(
        db_session,
        user_id=user.id,
        channel="email",
        template_key="cold_signup_day_1",
        slip_type="cold_signup",
        triggered_by="system_nightly",
        status="sent",
    )
    # day_3 should be unblocked.
    assert (
        await outreach_service.was_sent_recently(
            db_session, user_id=user.id, template_key="cold_signup_day_3"
        )
        is False
    )


@pytest.mark.asyncio
async def test_mark_delivered_is_idempotent(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    entry = await outreach_service.record(
        db_session,
        user_id=user.id,
        channel="email",
        template_key="paid_silent_day_3",
        slip_type="paid_silent",
        triggered_by="system_nightly",
        external_id="sg_abc123",
        status="sent",
    )
    # First call updates.
    assert (
        await outreach_service.mark_delivered(
            db_session, external_id="sg_abc123"
        )
        is True
    )
    # Second call no-ops (already delivered).
    assert (
        await outreach_service.mark_delivered(
            db_session, external_id="sg_abc123"
        )
        is False
    )
    # Row state is consistent.
    refreshed = await db_session.get(OutreachLog, entry.id)
    assert refreshed is not None
    assert refreshed.delivered_at is not None
    assert refreshed.status == "delivered"


@pytest.mark.asyncio
async def test_failed_status_doesnt_block_retry(
    db_session: AsyncSession,
) -> None:
    """A previous failed send should not throttle a retry — the user
    didn't actually receive anything."""
    user = await _make_user(db_session)
    failed = OutreachLog(
        id=uuid.uuid4(),
        user_id=user.id,
        channel="email",
        template_key="paid_silent_day_3",
        slip_type="paid_silent",
        triggered_by="system_nightly",
        sent_at=datetime.now(UTC),
        status="failed",
        error="SendGrid 503",
    )
    db_session.add(failed)
    await db_session.commit()

    # Should NOT be throttled — failed sends are excluded.
    assert (
        await outreach_service.was_sent_recently(
            db_session, user_id=user.id, template_key="paid_silent_day_3"
        )
        is False
    )


@pytest.mark.asyncio
async def test_list_for_user_orders_newest_first(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    # Insert three outreaches with explicit older timestamps.
    base = datetime.now(UTC)
    for i, days_ago in enumerate([10, 5, 1]):
        db_session.add(
            OutreachLog(
                id=uuid.uuid4(),
                user_id=user.id,
                channel="email",
                template_key=f"template_{i}",
                slip_type=None,
                triggered_by="admin_manual",
                sent_at=base - timedelta(days=days_ago),
                status="sent",
            )
        )
    await db_session.commit()

    rows = await outreach_service.list_for_user(db_session, user_id=user.id)
    assert len(rows) == 3
    # Newest first ordering.
    assert rows[0].template_key == "template_2"  # 1 day ago
    assert rows[1].template_key == "template_1"  # 5 days ago
    assert rows[2].template_key == "template_0"  # 10 days ago
