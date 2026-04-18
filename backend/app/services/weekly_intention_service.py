"""Weekly cadence prompts (P3 3B #151).

Student records ≤3 focus items for the week. A weekly Celery task on
Sunday reminds them (via existing weekly-letters integration). The
API here is the storage + retrieval layer.

Pure helpers on top; async loaders below.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weekly_intention import WeeklyIntention

_MAX_FOCUS_ITEMS = 3


def week_starting(d: date) -> date:
    """Monday of the week containing `d` (ISO week, 0=Mon)."""
    return d - timedelta(days=d.weekday())


def current_week_starting(now: datetime | None = None) -> date:
    effective = now or datetime.now(timezone.utc)
    return week_starting(effective.date())


def normalize_focus_items(items: Sequence[str]) -> list[str]:
    """Strip, de-dup case-insensitively, drop empties, cap at 3."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        cleaned = (raw or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned[:280])
        if len(out) >= _MAX_FOCUS_ITEMS:
            break
    return out


async def upsert_weekly_intentions(
    db: AsyncSession,
    *,
    user_id: UUID,
    items: Sequence[str],
    week: date | None = None,
) -> list[WeeklyIntention]:
    """Replace the user's intentions for the given week with `items`.

    Empty `items` clears the week. Existing rows are deleted first to
    keep the slot numbering clean.
    """
    target_week = week or current_week_starting()
    cleaned = normalize_focus_items(items)

    await db.execute(
        delete(WeeklyIntention).where(
            WeeklyIntention.user_id == user_id,
            WeeklyIntention.week_starting == target_week,
        )
    )

    rows: list[WeeklyIntention] = []
    for idx, text in enumerate(cleaned, start=1):
        row = WeeklyIntention(
            user_id=user_id,
            week_starting=target_week,
            slot=idx,
            text=text,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    for r in rows:
        await db.refresh(r)
    return rows


async def load_weekly_intentions(
    db: AsyncSession, *, user_id: UUID, week: date | None = None
) -> list[WeeklyIntention]:
    target_week = week or current_week_starting()
    result = await db.execute(
        select(WeeklyIntention)
        .where(
            WeeklyIntention.user_id == user_id,
            WeeklyIntention.week_starting == target_week,
        )
        .order_by(WeeklyIntention.slot.asc())
    )
    return list(result.scalars().all())


__all__ = [
    "current_week_starting",
    "load_weekly_intentions",
    "normalize_focus_items",
    "upsert_weekly_intentions",
    "week_starting",
]
