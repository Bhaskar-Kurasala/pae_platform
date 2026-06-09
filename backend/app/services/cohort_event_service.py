"""Cohort event log — feeds the "Cohort, live" rail and peers chips on Today.

Append-only. Reads are scoped to the most recent N events; optional level
slug filter so a Python Developer doesn't see Data Engineer level-up noise.
Handles are masked to first-name + last-initial so we never leak email
prefixes into the public stream.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cohort_event import CohortEvent
from app.models.user import User


def mask_handle(full_name: str | None, fallback: str = "A peer") -> str:
    if not full_name:
        return fallback
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return fallback
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


async def record_event(
    db: AsyncSession,
    *,
    kind: str,
    actor: User | None,
    label: str,
    occurred_at: datetime | None = None,
    payload: dict | None = None,
    level_slug: str | None = None,
) -> CohortEvent:
    actor_handle = mask_handle(actor.full_name if actor else None)
    event = CohortEvent(
        kind=kind,
        actor_id=actor.id if actor else None,
        actor_handle=actor_handle,
        label=label,
        payload=payload,
        occurred_at=occurred_at or datetime.now(UTC),
        level_slug=level_slug,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def recent_events(
    db: AsyncSession,
    *,
    limit: int = 5,
    level_slug: str | None = None,
    kinds: Sequence[str] | None = None,
) -> list[CohortEvent]:
    q = select(CohortEvent).order_by(desc(CohortEvent.occurred_at)).limit(limit)
    if level_slug is not None:
        q = q.where(CohortEvent.level_slug == level_slug)
    if kinds:
        q = q.where(CohortEvent.kind.in_(list(kinds)))
    result = await db.execute(q)
    return list(result.scalars().all())


async def peers_active_today(
    db: AsyncSession,
    *,
    level_slug: str | None = None,
    now: datetime | None = None,
) -> int:
    """Count of distinct cohort actors with any event in the last 24h.

    Used to populate "12 peers at your level today" without pretending to
    do realtime presence — events are a faithful proxy.
    """
    current = now or datetime.now(UTC)
    since = current - timedelta(hours=24)
    q = select(func.count(func.distinct(CohortEvent.actor_id))).where(
        CohortEvent.actor_id.is_not(None),
        CohortEvent.occurred_at >= since,
    )
    if level_slug is not None:
        q = q.where(CohortEvent.level_slug == level_slug)
    result = await db.execute(q)
    return int(result.scalar() or 0)


async def promotions_today(
    db: AsyncSession,
    *,
    level_slug: str | None = None,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC)
    since = current - timedelta(hours=24)
    q = select(func.count(CohortEvent.id)).where(
        CohortEvent.kind == "level_up",
        CohortEvent.occurred_at >= since,
    )
    if level_slug is not None:
        q = q.where(CohortEvent.level_slug == level_slug)
    result = await db.execute(q)
    return int(result.scalar() or 0)


# Pure helpers — kept here for direct unit-testing without a DB session.
def coerce_uuid(maybe: uuid.UUID | str | None) -> uuid.UUID | None:
    if maybe is None:
        return None
    if isinstance(maybe, uuid.UUID):
        return maybe
    return uuid.UUID(str(maybe))
