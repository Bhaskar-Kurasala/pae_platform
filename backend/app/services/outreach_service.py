"""F3 — OutreachService: throttle + audit every system or admin send.

The single chokepoint for "did we send X to user Y recently" — used by
F5 email service, F9 nightly automation, and F4 admin console
per-student outreach feed.

Three rules baked in:
  1. Every send writes a row to outreach_log BEFORE the network call.
     If the network call fails, the row's status flips to 'failed' so
     a later admin retry knows what happened.
  2. Throttle: per (user_id, template_key) window. Default 7 days. F5
     can override per-template (a "first session reminder day 1" and
     "first session reminder day 3" are different template_keys, both
     allowed for the same user).
  3. Webhooks (delivery, open, reply): match by external_id and update
     in place. Idempotent — same webhook fired twice doesn't double-
     update.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog

log = structlog.get_logger()

DEFAULT_THROTTLE_DAYS = 7


def _now() -> datetime:
    return datetime.now(UTC)


async def record(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel: str,
    template_key: str | None,
    slip_type: str | None,
    triggered_by: str,
    triggered_by_user_id: uuid.UUID | None = None,
    body_preview: str | None = None,
    external_id: str | None = None,
    status: str = "pending",
) -> OutreachLog:
    """Insert one outreach row. Caller flips status to 'sent' / 'failed'
    after the network attempt. body_preview should be the first 200
    chars of the rendered message — full body is NOT stored to avoid
    PII bloat."""
    entry = OutreachLog(
        id=uuid.uuid4(),
        user_id=user_id,
        channel=channel,
        template_key=template_key,
        slip_type=slip_type,
        triggered_by=triggered_by,
        triggered_by_user_id=triggered_by_user_id,
        sent_at=_now(),
        body_preview=(body_preview[:200] if body_preview else None),
        external_id=external_id,
        status=status,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    log.info(
        "outreach.recorded",
        user_id=str(user_id),
        channel=channel,
        template_key=template_key,
        status=status,
    )
    return entry


async def was_sent_recently(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    template_key: str,
    within_days: int = DEFAULT_THROTTLE_DAYS,
) -> bool:
    """Throttle check: has this template been sent to this user within
    the window? Used by F5 + F9 to avoid spamming a user.

    Excludes status='failed' so a previous failure doesn't block a
    retry. Excludes status='mocked' (dev mode) so local testing
    doesn't get throttled by stub sends.
    """
    cutoff = _now() - timedelta(days=within_days)
    q = await db.execute(
        select(OutreachLog.id)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.template_key == template_key,
            OutreachLog.sent_at >= cutoff,
            OutreachLog.status.in_(["pending", "sent", "delivered"]),
        )
        .limit(1)
    )
    return q.scalar() is not None


async def update_status(
    db: AsyncSession,
    *,
    log_id: uuid.UUID,
    status: str,
    external_id: str | None = None,
    error: str | None = None,
) -> None:
    """Update a row's status after the network attempt completes. Used
    by F5 right after the SendGrid call returns."""
    entry = await db.get(OutreachLog, log_id)
    if entry is None:
        return
    entry.status = status
    if external_id is not None:
        entry.external_id = external_id
    if error is not None:
        entry.error = error
    await db.commit()


async def mark_delivered(
    db: AsyncSession, *, external_id: str
) -> bool:
    """SendGrid 'delivered' webhook handler. Idempotent — same webhook
    fired twice updates the timestamp once and no-ops the second time
    (the WHERE clause filters out already-delivered rows)."""
    q = await db.execute(
        select(OutreachLog).where(
            OutreachLog.external_id == external_id,
            OutreachLog.delivered_at.is_(None),
        )
    )
    entry = q.scalar_one_or_none()
    if entry is None:
        return False
    entry.delivered_at = _now()
    entry.status = "delivered"
    await db.commit()
    return True


async def mark_opened(db: AsyncSession, *, external_id: str) -> bool:
    """SendGrid 'open' webhook handler. Same idempotency contract."""
    q = await db.execute(
        select(OutreachLog).where(
            OutreachLog.external_id == external_id,
            OutreachLog.opened_at.is_(None),
        )
    )
    entry = q.scalar_one_or_none()
    if entry is None:
        return False
    entry.opened_at = _now()
    await db.commit()
    return True


async def list_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 50,
) -> list[OutreachLog]:
    """All outreach to one user, newest first. Powers the
    per-student outreach feed in F4 admin console."""
    q = await db.execute(
        select(OutreachLog)
        .where(OutreachLog.user_id == user_id)
        .order_by(desc(OutreachLog.sent_at))
        .limit(limit)
    )
    return list(q.scalars().all())
