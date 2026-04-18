"""Receipts service — weekly learning summaries and diffs."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import Date as SADate
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.growth_snapshot import GrowthSnapshot
from app.models.reflection import Reflection
from app.models.skill import Skill
from app.models.user_skill_state import UserSkillState

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pure helpers — unit-testable without a DB
# ---------------------------------------------------------------------------


def compute_week_over_week(
    *,
    prior_lessons: int | None,
    current_lessons: int,
) -> dict[str, Any]:
    """Return delta and trend for lessons completed week-over-week."""
    if prior_lessons is None:
        return {"lessons_delta": None, "lessons_trend": "first_week"}
    delta = current_lessons - prior_lessons
    trend: Literal["up", "down", "flat"] = "up" if delta > 0 else "down" if delta < 0 else "flat"
    return {"lessons_delta": delta, "lessons_trend": trend}


def aggregate_reflections(moods: list[str]) -> dict[str, Any]:
    """Summarise a list of mood strings into counts and dominant mood."""
    counts: Counter[str] = Counter(moods)
    dominant = counts.most_common(1)[0][0] if counts else "none"
    return {"mood_counts": dict(counts), "dominant_mood": dominant}


# ---------------------------------------------------------------------------
# DB helpers — require AsyncSession
# ---------------------------------------------------------------------------


async def fetch_week_over_week(
    db: AsyncSession,
    user_id: uuid.UUID,
    week_start: datetime,
) -> dict[str, Any]:
    """Compare current-week lesson count against prior week from snapshots."""
    now = datetime.now(UTC)
    prior_week_end = week_start
    prior_week_start = prior_week_end - timedelta(days=7)

    # Current week: lessons from growth snapshot where week_ending is in current window
    # or fall back to None (first week)
    current_snap = (
        await db.execute(
            select(GrowthSnapshot.lessons_completed)
            .where(
                GrowthSnapshot.user_id == user_id,
                GrowthSnapshot.week_ending >= week_start.date(),
                GrowthSnapshot.week_ending <= now.date(),
            )
            .order_by(GrowthSnapshot.week_ending.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    prior_snap = (
        await db.execute(
            select(GrowthSnapshot.lessons_completed)
            .where(
                GrowthSnapshot.user_id == user_id,
                GrowthSnapshot.week_ending >= prior_week_start.date(),
                GrowthSnapshot.week_ending < prior_week_end.date(),
            )
            .order_by(GrowthSnapshot.week_ending.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    current_lessons: int = current_snap if current_snap is not None else 0
    wow = compute_week_over_week(
        prior_lessons=prior_snap,
        current_lessons=current_lessons,
    )
    log.info(
        "receipts.wow_computed",
        user_id=str(user_id),
        trend=wow["lessons_trend"],
    )
    return wow


async def fetch_skills_touched(
    db: AsyncSession,
    user_id: uuid.UUID,
    week_start: datetime,
) -> list[dict[str, Any]]:
    """Return skills touched this week with their current confidence."""
    rows = (
        await db.execute(
            select(Skill.id, Skill.name, UserSkillState.confidence)
            .join(UserSkillState, UserSkillState.skill_id == Skill.id)
            .where(
                UserSkillState.user_id == user_id,
                UserSkillState.last_touched_at >= week_start,
            )
            .order_by(UserSkillState.confidence.desc())
        )
    ).all()

    return [
        {"id": str(r.id), "name": r.name, "mastery": round(float(r.confidence), 2)} for r in rows
    ]


async def fetch_portfolio_items(
    db: AsyncSession,
    user_id: uuid.UUID,
    week_start: datetime,
) -> list[dict[str, Any]]:
    """Return passed exercise submissions this week."""
    rows = (
        await db.execute(
            select(ExerciseSubmission.id, Exercise.title, ExerciseSubmission.created_at)
            .join(Exercise, ExerciseSubmission.exercise_id == Exercise.id)
            .where(
                ExerciseSubmission.student_id == user_id,
                ExerciseSubmission.created_at >= week_start,
                ExerciseSubmission.status == "passed",
            )
            .order_by(ExerciseSubmission.created_at.desc())
        )
    ).all()

    items = [
        {
            "id": str(r.id),
            "exercise_title": r.title,
            "submitted_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    log.info(
        "receipts.portfolio_items_computed",
        user_id=str(user_id),
        count=len(items),
    )
    return items


async def fetch_reflection_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    week_start: datetime,
) -> dict[str, Any]:
    """Aggregate reflection moods for this week."""
    rows = (
        await db.execute(
            select(Reflection.mood).where(
                Reflection.user_id == user_id,
                Reflection.created_at >= week_start,
            )
        )
    ).all()
    moods = [r[0] for r in rows if r[0]]
    return aggregate_reflections(moods)


async def fetch_daily_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    week_start: datetime,
) -> list[dict[str, Any]]:
    """Return per-day action counts (1 action ≈ 5 min) for the past 7 days."""
    rows = (
        await db.execute(
            select(
                cast(AgentAction.created_at, SADate).label("day"),
                func.count(AgentAction.id).label("actions"),
            )
            .where(
                AgentAction.student_id == user_id,
                AgentAction.created_at >= week_start,
            )
            .group_by("day")
            .order_by("day")
        )
    ).all()

    return [{"day": str(r.day), "minutes": r.actions * 5} for r in rows]


async def fetch_next_week_suggestion(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Return the weakest recently-active skill as a focus suggestion."""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    row = (
        await db.execute(
            select(Skill.name, UserSkillState.confidence)
            .join(UserSkillState, UserSkillState.skill_id == Skill.id)
            .where(
                UserSkillState.user_id == user_id,
                UserSkillState.last_touched_at >= cutoff,
                UserSkillState.confidence < 0.8,
            )
            .order_by(UserSkillState.confidence.asc())
            .limit(1)
        )
    ).first()

    suggestion = (
        {"skill_name": row.name, "current_mastery": round(float(row.confidence), 2)}
        if row
        else None
    )
    log.info(
        "receipts.suggestion_generated",
        user_id=str(user_id),
        has_suggestion=suggestion is not None,
    )
    return suggestion
