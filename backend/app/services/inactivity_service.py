"""Inactivity re-engagement (P3 3B #152).

Finds students with no `agent_actions` for ≥N days and flags them for
the existing `disrupt_prevention` agent. The Celery task reads this
list and logs it; actual agent invocation is left to the existing
chat/agents API so we don't duplicate the LLM plumbing.

Pure helpers up top; async DB loader below.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction
from app.models.user import User

_INACTIVE_THRESHOLD_DAYS = 7


@dataclass(frozen=True)
class InactiveStudent:
    user_id: UUID
    days_inactive: int
    last_activity_at: datetime | None


def is_inactive(
    last_activity_at: datetime | None,
    *,
    now: datetime,
    threshold_days: int = _INACTIVE_THRESHOLD_DAYS,
) -> bool:
    """Never-active students count as inactive too — they need the nudge most."""
    if last_activity_at is None:
        return True
    if last_activity_at.tzinfo is None:
        last_activity_at = last_activity_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - last_activity_at) >= timedelta(days=threshold_days)


def days_since(
    last_activity_at: datetime | None, *, now: datetime
) -> int:
    if last_activity_at is None:
        return 9999
    if last_activity_at.tzinfo is None:
        last_activity_at = last_activity_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, (now - last_activity_at).days)


def filter_inactive(
    rows: Sequence[tuple[UUID, datetime | None]],
    *,
    now: datetime,
    threshold_days: int = _INACTIVE_THRESHOLD_DAYS,
) -> list[InactiveStudent]:
    out: list[InactiveStudent] = []
    for user_id, last_at in rows:
        if is_inactive(last_at, now=now, threshold_days=threshold_days):
            out.append(
                InactiveStudent(
                    user_id=user_id,
                    days_inactive=days_since(last_at, now=now),
                    last_activity_at=last_at,
                )
            )
    return out


async def load_inactive_students(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    threshold_days: int = _INACTIVE_THRESHOLD_DAYS,
) -> list[InactiveStudent]:
    """All active users with no agent_actions in the last N days."""
    effective_now = now or datetime.now(timezone.utc)
    last_activity = (
        select(
            AgentAction.student_id.label("uid"),
            func.max(AgentAction.created_at).label("last_at"),
        )
        .group_by(AgentAction.student_id)
        .subquery()
    )
    stmt = (
        select(User.id, last_activity.c.last_at)
        .outerjoin(last_activity, last_activity.c.uid == User.id)
        .where(User.is_active.is_(True))
    )
    result = await db.execute(stmt)
    rows = [(r[0], r[1]) for r in result.all()]
    return filter_inactive(
        rows, now=effective_now, threshold_days=threshold_days
    )


__all__ = [
    "InactiveStudent",
    "days_since",
    "filter_inactive",
    "is_inactive",
    "load_inactive_students",
]
