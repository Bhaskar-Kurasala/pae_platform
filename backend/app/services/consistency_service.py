"""Consistency surfacing for the Today screen (P3 3A-14).

Replaces the streak widget's loss-aversion framing with an honest count:
"You showed up N of 7 days last week." Any `agent_actions` row in the
window counts as a show-up — we explicitly do not weight or grade the
activity.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction
from app.models.exercise_submission import ExerciseSubmission
from app.models.student_progress import StudentProgress

_WINDOW_DAYS = 7


def window_bounds(
    now: datetime, *, window_days: int = _WINDOW_DAYS
) -> tuple[datetime, datetime]:
    """Return (start, end) for the rolling N-day window ending at `now`.

    Start is floored to midnight UTC so a single day counts as one bucket
    regardless of when during the day the action landed.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    end_day = now.astimezone(UTC).date()
    start_day = end_day - timedelta(days=window_days - 1)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=UTC)
    return start, now


def count_active_days(
    action_timestamps: Iterable[datetime],
    *,
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Count distinct UTC days in [start, end] that had at least one action."""
    days: set[date] = set()
    for ts in action_timestamps:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts < window_start or ts > window_end:
            continue
        days.add(ts.astimezone(UTC).date())
    return len(days)


async def load_consistency(
    db: AsyncSession,
    *,
    user_id: UUID,
    now: datetime | None = None,
    window_days: int = _WINDOW_DAYS,
) -> tuple[int, int]:
    """Return (days_active, window_days) for a user over the last N days.

    A "show-up" is any of: an agent action, a completed lesson, or an
    exercise submission. Unioning the three sources fixes the false-zero
    case where a learner watches videos and submits exercises without
    triggering an agent (the original implementation only counted
    `agent_actions`).
    """
    current = now or datetime.now(UTC)
    start, end = window_bounds(current, window_days=window_days)

    agent_q = select(
        func.date(AgentAction.created_at).label("d"),
    ).where(
        AgentAction.student_id == user_id,
        AgentAction.created_at >= start,
        AgentAction.created_at <= end,
    )
    progress_q = select(
        func.date(StudentProgress.completed_at).label("d"),
    ).where(
        StudentProgress.student_id == user_id,
        StudentProgress.completed_at.is_not(None),
        StudentProgress.completed_at >= start,
        StudentProgress.completed_at <= end,
    )
    submission_q = select(
        func.date(ExerciseSubmission.created_at).label("d"),
    ).where(
        ExerciseSubmission.student_id == user_id,
        ExerciseSubmission.created_at >= start,
        ExerciseSubmission.created_at <= end,
    )

    union_q = union_all(agent_q, progress_q, submission_q).subquery()
    result = await db.execute(
        select(func.count(func.distinct(union_q.c.d)))
    )
    count = result.scalar() or 0
    return int(count), window_days
