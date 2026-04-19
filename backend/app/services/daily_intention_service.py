"""Daily intention service (P3 3A-11).

A single-line "what do you want to do today" prompt on the Today
screen. One row per (user, date) — later edits on the same day
overwrite the row, a fresh day shows a blank prompt.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_intention import DailyIntention

log = structlog.get_logger()


def normalize_text(raw: str) -> str:
    """Strip surrounding whitespace. Caller has already length-checked."""
    return raw.strip()


def today_in_utc(now: datetime | None = None) -> date:
    """Single choke-point for "today" so we don't mix timezones.

    We store intention_date in UTC to match every other date column in
    the schema — UX can localize for display, but persisted dates are
    UTC.
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).date()


async def get_for_date(
    db: AsyncSession, *, user_id: uuid.UUID, on: date
) -> DailyIntention | None:
    return (
        await db.execute(
            select(DailyIntention).where(
                DailyIntention.user_id == user_id,
                DailyIntention.intention_date == on,
            )
        )
    ).scalar_one_or_none()


async def upsert_today(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    text: str,
    now: datetime | None = None,
    intention_date: date | None = None,
) -> DailyIntention:
    """Create or overwrite today's intention for this user.

    DISC-17: Accept a client-supplied `intention_date` so users past the UTC
    boundary still file the row against their *local* date. Falls back to UTC
    when absent.
    """
    today = intention_date if intention_date is not None else today_in_utc(now)
    clean = normalize_text(text)
    existing = await get_for_date(db, user_id=user_id, on=today)
    if existing is None:
        row = DailyIntention(user_id=user_id, intention_date=today, text=clean)
        db.add(row)
    else:
        existing.text = clean
        row = existing
    await db.commit()
    await db.refresh(row)
    log.info(
        "today.intention_set",
        user_id=str(user_id),
        intention_length=len(clean),
        date=str(today),
    )
    return row
