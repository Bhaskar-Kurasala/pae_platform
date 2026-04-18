"""Weekly growth snapshot service (P1-C-2).

Computes a per-user snapshot of the prior week. Used by the Sunday-midnight
Celery beat job and by tests. A snapshot is idempotent per (user, week_ending)
— re-running simply upserts the same row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.growth_snapshot import GrowthSnapshot
from app.models.quiz_result import QuizResult
from app.models.reflection import Reflection
from app.models.skill import Skill
from app.models.student_progress import StudentProgress
from app.models.user_skill_state import UserSkillState

log = structlog.get_logger()


@dataclass
class SnapshotStats:
    user_id: uuid.UUID
    week_ending: date
    lessons_completed: int
    skills_touched: int
    streak_days: int
    top_concept: str | None
    payload: dict[str, Any]


def last_week_window(now: datetime | None = None) -> tuple[datetime, datetime, date]:
    """Return (start, end, week_ending) for the week just ended (Mon–Sun UTC).

    `week_ending` is the Sunday UTC of that week (inclusive).
    `start` is Monday 00:00 UTC, `end` is the following Monday 00:00 UTC.
    """
    ref = now or datetime.now(UTC)
    # Sunday of the week that just ended is today's date if today is a Monday,
    # otherwise it's the most-recent Sunday.
    today = ref.date()
    # weekday(): Mon=0 .. Sun=6
    days_since_sunday = (today.weekday() + 1) % 7  # 0 if today is Sun
    week_ending = today - timedelta(days=days_since_sunday or 7)
    start_date = week_ending - timedelta(days=6)
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(
        week_ending + timedelta(days=1), datetime.min.time(), tzinfo=UTC
    )
    return start, end, week_ending


def _as_utc(ts: datetime) -> datetime:
    """Normalize a datetime to tz-aware UTC.

    SQLite strips timezone info from DateTime(timezone=True) columns on readback,
    so values that were stored as UTC-aware come back naive. Treat naive
    timestamps as UTC (matches how they were written by app code).
    """
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _compute_streak_days(timestamps: list[datetime | None], ref: datetime) -> int:
    """Consecutive-days streak ending today (or yesterday — grace window)."""
    days: set[date] = set()
    for ts in timestamps:
        if ts is None:
            continue
        days.add(_as_utc(ts).astimezone(UTC).date())
    if not days:
        return 0

    today = ref.astimezone(UTC).date()
    yesterday = today - timedelta(days=1)
    if today in days:
        cursor = today
    elif yesterday in days:
        cursor = yesterday
    else:
        return 0

    count = 0
    while cursor in days:
        count += 1
        cursor = cursor - timedelta(days=1)
    return count


async def compute_snapshot(
    db: AsyncSession,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> SnapshotStats:
    """Compute — but do NOT persist — a growth snapshot for the week just ended."""
    start, end, week_ending = last_week_window(now)

    # Lessons completed in-window
    lessons_completed_q = select(func.count(StudentProgress.id)).where(
        StudentProgress.student_id == user_id,
        StudentProgress.status == "completed",
        StudentProgress.completed_at.is_not(None),
        StudentProgress.completed_at >= start,
        StudentProgress.completed_at < end,
    )
    lessons_completed = int((await db.execute(lessons_completed_q)).scalar() or 0)

    # Skill states for this user — basis for skills_touched + streak + top concept
    skill_states_q = select(UserSkillState).where(UserSkillState.user_id == user_id)
    skill_states = list((await db.execute(skill_states_q)).scalars().all())

    skills_touched = sum(
        1
        for s in skill_states
        if s.last_touched_at is not None
        and start <= _as_utc(s.last_touched_at) < end
    )

    streak_days = _compute_streak_days(
        [s.last_touched_at for s in skill_states],
        ref=now or datetime.now(UTC),
    )

    # Top concept: the skill with the highest confidence that was touched in-window.
    top_concept: str | None = None
    in_window = [
        s
        for s in skill_states
        if s.last_touched_at is not None
        and start <= _as_utc(s.last_touched_at) < end
    ]
    if in_window:
        in_window.sort(key=lambda s: s.confidence, reverse=True)
        top_skill_id = in_window[0].skill_id
        skill = (
            await db.execute(select(Skill).where(Skill.id == top_skill_id))
        ).scalar_one_or_none()
        if skill is not None:
            top_concept = skill.name

    # Payload: quiz scores + reflection count in-window
    quiz_q = select(func.count(QuizResult.id), func.avg(QuizResult.score)).where(
        QuizResult.student_id == user_id,
        QuizResult.created_at >= start,
        QuizResult.created_at < end,
    )
    quiz_count, quiz_avg = (await db.execute(quiz_q)).one()

    reflection_q = select(func.count(Reflection.id)).where(
        Reflection.user_id == user_id,
        Reflection.created_at >= start,
        Reflection.created_at < end,
    )
    reflection_count = int((await db.execute(reflection_q)).scalar() or 0)

    payload: dict[str, Any] = {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "quiz_attempts": int(quiz_count or 0),
        "quiz_avg_score": float(quiz_avg) if quiz_avg is not None else None,
        "reflections": reflection_count,
    }

    return SnapshotStats(
        user_id=user_id,
        week_ending=week_ending,
        lessons_completed=lessons_completed,
        skills_touched=skills_touched,
        streak_days=streak_days,
        top_concept=top_concept,
        payload=payload,
    )


async def upsert_snapshot(
    db: AsyncSession, stats: SnapshotStats
) -> GrowthSnapshot:
    """Insert-or-update the snapshot row, then return the persisted record.

    Uses a select-then-insert-or-update pattern rather than a dialect-specific
    ON CONFLICT clause so the same code path works under Postgres (prod) and
    SQLite (tests). The unique constraint on (user_id, week_ending) still
    guards against concurrent duplicate inserts — we'd let the IntegrityError
    bubble up rather than swallow it.
    """
    existing = (
        await db.execute(
            select(GrowthSnapshot).where(
                GrowthSnapshot.user_id == stats.user_id,
                GrowthSnapshot.week_ending == stats.week_ending,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        row = GrowthSnapshot(
            user_id=stats.user_id,
            week_ending=stats.week_ending,
            lessons_completed=stats.lessons_completed,
            skills_touched=stats.skills_touched,
            streak_days=stats.streak_days,
            top_concept=stats.top_concept,
            payload=stats.payload,
        )
        db.add(row)
    else:
        existing.lessons_completed = stats.lessons_completed
        existing.skills_touched = stats.skills_touched
        existing.streak_days = stats.streak_days
        existing.top_concept = stats.top_concept
        existing.payload = stats.payload
        row = existing

    await db.commit()
    await db.refresh(row)
    return row


async def build_and_persist(
    db: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> GrowthSnapshot:
    stats = await compute_snapshot(db, user_id, now=now)
    snap = await upsert_snapshot(db, stats)
    log.info(
        "growth_snapshot.persisted",
        user_id=str(user_id),
        week_ending=str(stats.week_ending),
        lessons=stats.lessons_completed,
        skills=stats.skills_touched,
        streak=stats.streak_days,
    )
    return snap
