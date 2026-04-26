"""Learning session service — drives "Session N" + step state on Today.

A session opens whenever the user returns to Today after a gap > GAP_MINUTES,
or explicitly via `start_session`. Step timestamps are flipped via
`mark_step` and surface on the rail "What unlocks next" timeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning_session import LearningSession

GAP_MINUTES = 90  # idle gap that opens a fresh session


def _now() -> datetime:
    return datetime.now(UTC)


StepName = Literal["warmup", "lesson", "reflect"]


async def latest_session(
    db: AsyncSession, *, user_id: uuid.UUID
) -> LearningSession | None:
    """Return the most-recent session row, if any. Read-only."""
    result = await db.execute(
        select(LearningSession)
        .where(LearningSession.user_id == user_id)
        .order_by(desc(LearningSession.started_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_or_open_session(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> LearningSession:
    """Return the active session (open or recent), opening a new one if stale.

    Idempotent for the typical case where the student already has a fresh
    session this hour. The unique (user_id, ordinal) constraint protects
    against two parallel opens.

    This call MUTATES (inserts a row when stale). Use `latest_session` for
    read-only paths (e.g. the GET aggregator) so passive page-loads don't
    accumulate phantom sessions.
    """
    current = now or _now()
    threshold = current - timedelta(minutes=GAP_MINUTES)

    latest = await latest_session(db, user_id=user_id)

    if latest is not None and (
        latest.ended_at is None
        and latest.started_at >= threshold
    ):
        return latest

    next_ordinal = 1
    if latest is not None:
        next_ordinal = int(latest.ordinal) + 1

    fresh = LearningSession(
        user_id=user_id,
        started_at=current,
        ordinal=next_ordinal,
    )
    db.add(fresh)
    await db.commit()
    await db.refresh(fresh)
    return fresh


def project_next_ordinal(latest: LearningSession | None) -> int:
    """Pure helper: what ordinal would the next opened session get?"""
    if latest is None:
        return 1
    return int(latest.ordinal) + 1


async def mark_step(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    step: StepName,
    now: datetime | None = None,
) -> LearningSession:
    """Stamp warmup/lesson/reflect completion on the active session."""
    current = now or _now()
    session = await get_or_open_session(db, user_id=user_id, now=current)
    field = f"{step}_done_at"
    if getattr(session, field) is None:
        setattr(session, field, current)
        # If reflect just landed, close the session.
        if step == "reflect":
            session.ended_at = current
        await db.commit()
        await db.refresh(session)
    return session


async def session_count_for_user(
    db: AsyncSession, *, user_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(func.count(LearningSession.id)).where(
            LearningSession.user_id == user_id
        )
    )
    return int(result.scalar() or 0)
