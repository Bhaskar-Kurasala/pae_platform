"""Today screen aggregator — assembles every value the Today UI needs.

Reuses existing services rather than duplicating logic. The aggregator owns
only orchestration + the few cross-cutting derivations (capstone projection,
current focus skill, milestone label).

All heavy queries are independent so we run them concurrently with
``asyncio.gather`` and let the SQLAlchemy session multiplex.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cohort_event import CohortEvent
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.skill import Skill
from app.models.srs_card import SRSCard
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.schemas.today_summary import (
    TodayCapstone,
    TodayCohortEvent,
    TodayConsistency,
    TodayCurrentFocus,
    TodayGoal,
    TodayIntention,
    TodayMicroWin,
    TodayMilestone,
    TodayProgress,
    TodayReadiness,
    TodaySession,
    TodaySummaryResponse,
    TodayUser,
)
from app.services.cohort_event_service import (
    peers_active_today,
    promotions_today,
    recent_events,
)
from app.services.consistency_service import load_consistency
from app.services.daily_intention_service import get_for_date, today_in_utc
from app.services.goal_contract_service import (
    GoalContractService,
    days_remaining,
)
from app.services.learning_session_service import (
    latest_session,
    project_next_ordinal,
)
from app.services.micro_wins_service import load_micro_wins
from app.services.progress_service import ProgressService

DEFAULT_LEVEL_SLUG = "python_developer"


def _first_name(user: User) -> str:
    if not user.full_name:
        return ""
    return user.full_name.strip().split()[0]


async def _capstone_for_user(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> TodayCapstone:
    """Find the soonest-due capstone the user has touched, with draft stats."""
    capstone_q = (
        select(Exercise)
        .where(
            Exercise.is_capstone.is_(True),
            Exercise.is_deleted.is_(False),
        )
        .order_by(
            # NULL due_at sorts last; earliest due first.
            Exercise.due_at.is_(None).asc(),
            Exercise.due_at.asc(),
            Exercise.created_at.asc(),
        )
        .limit(1)
    )
    capstone = (await db.execute(capstone_q)).scalar_one_or_none()
    if capstone is None:
        return TodayCapstone()

    sub_q = (
        select(ExerciseSubmission)
        .where(
            ExerciseSubmission.student_id == user_id,
            ExerciseSubmission.exercise_id == capstone.id,
        )
        .order_by(desc(ExerciseSubmission.created_at))
    )
    submissions = list((await db.execute(sub_q)).scalars().all())
    drafts_count = len(submissions)
    draft_quality: int | None = None
    for sub in submissions:
        if sub.score is not None:
            draft_quality = int(sub.score)
            break

    days_to_due: int | None = None
    if capstone.due_at is not None:
        due = capstone.due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        days_to_due = max(0, (due - now).days)

    return TodayCapstone(
        exercise_id=capstone.id,
        title=capstone.title,
        days_to_due=days_to_due,
        draft_quality=draft_quality,
        drafts_count=drafts_count,
    )


async def _current_focus(
    db: AsyncSession, user_id: uuid.UUID
) -> TodayCurrentFocus:
    """Most recently touched skill with a friendly blurb."""
    q = (
        select(UserSkillState, Skill)
        .join(Skill, Skill.id == UserSkillState.skill_id)
        .where(
            UserSkillState.user_id == user_id,
            UserSkillState.last_touched_at.is_not(None),
        )
        .order_by(desc(UserSkillState.last_touched_at))
        .limit(1)
    )
    row = (await db.execute(q)).first()
    if row is None:
        return TodayCurrentFocus()
    _state, skill = row
    return TodayCurrentFocus(
        skill_slug=skill.slug,
        skill_name=skill.name,
        skill_blurb=(skill.description or "")[:140] or None,
    )


async def _due_card_count(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> int:
    result = await db.execute(
        select(func.count(SRSCard.id)).where(
            SRSCard.user_id == user_id,
            SRSCard.next_due_at <= now,
        )
    )
    return int(result.scalar() or 0)


async def _readiness(db: AsyncSession, user_id: uuid.UUID) -> TodayReadiness:
    """Best-effort readiness score + week-over-week delta from north-star.

    Falls back to a zeroed payload when readiness hasn't been seeded yet —
    we never want this to block the Today screen.

    The north-star "rate" we surface is the completion-within-24h rate
    (the platform's product north star). Delta is this-week minus the
    prior 7-day window so we can render "+8 this week" honestly.
    """
    try:
        from app.services.readiness_north_star import compute_north_star_rate

        current = await compute_north_star_rate(db, window_days=7)
        prior = await compute_north_star_rate(db, window_days=14)
        current_pct = int(
            round(getattr(current, "completion_within_24h_rate", 0.0) * 100)
        )
        prior_pct = int(
            round(getattr(prior, "completion_within_24h_rate", 0.0) * 100)
        )
        delta = current_pct - prior_pct
        return TodayReadiness(current=current_pct, delta_week=delta)
    except Exception:
        return TodayReadiness()


def _milestone(goal: TodayGoal) -> TodayMilestone:
    label = goal.target_role or (goal.success_statement or "your next role")
    return TodayMilestone(label=label, days=goal.days_remaining)


async def build_today_summary(
    db: AsyncSession, *, user: User, now: datetime | None = None
) -> TodaySummaryResponse:
    current = now or datetime.now(UTC)

    contract = await GoalContractService(db).get_for_user(user)
    goal = TodayGoal()
    if contract is not None:
        goal = TodayGoal(
            success_statement=contract.success_statement,
            target_role=contract.target_role,
            days_remaining=days_remaining(contract, now=current),
            motivation=contract.motivation,
        )

    progress_resp = await ProgressService(db).get_student_progress(user)
    progress = TodayProgress(
        overall_percentage=progress_resp.overall_progress,
        lessons_completed_total=progress_resp.lessons_completed_total,
        lessons_total=progress_resp.lessons_total,
        today_unlock_percentage=progress_resp.today_unlock_percentage,
        active_course_id=progress_resp.active_course_id,
        active_course_title=progress_resp.active_course_title,
        next_lesson_id=progress_resp.next_lesson_id,
        next_lesson_title=progress_resp.next_lesson_title,
    )

    days_active, window_days = await load_consistency(
        db, user_id=user.id, now=current
    )
    consistency = TodayConsistency(
        days_active=days_active, window_days=window_days
    )

    intention_row = await get_for_date(
        db, user_id=user.id, on=today_in_utc(current)
    )
    intention = TodayIntention(text=intention_row.text if intention_row else None)

    # READ-ONLY session lookup. The Today summary GET endpoint must not write
    # — every passive page-load was previously inserting a row, which leaks
    # phantom sessions for crawlers + stale tabs. Sessions only open when the
    # user actually marks a step (mark_step → get_or_open_session).
    last = await latest_session(db, user_id=user.id)
    if last is not None and (
        last.ended_at is None
    ):
        session = TodaySession(
            id=last.id,
            ordinal=last.ordinal,
            started_at=last.started_at,
            warmup_done_at=last.warmup_done_at,
            lesson_done_at=last.lesson_done_at,
            reflect_done_at=last.reflect_done_at,
        )
    else:
        # Either no sessions yet, or the latest is closed. Project the next
        # ordinal so the UI displays "Session N+1" without a write — the row
        # appears on the first mark_step call.
        session = TodaySession(
            id=None,
            ordinal=project_next_ordinal(last),
            started_at=None,
            warmup_done_at=None,
            lesson_done_at=None,
            reflect_done_at=None,
        )

    # Cross-cutting projections — independent, so fan out concurrently.
    capstone_task = _capstone_for_user(db, user.id, now=current)
    focus_task = _current_focus(db, user.id)
    due_task = _due_card_count(db, user.id, now=current)
    readiness_task = _readiness(db, user.id)
    micro_wins_task = load_micro_wins(db, user_id=user.id, now=current)
    cohort_task = recent_events(db, limit=5)
    peers_task = peers_active_today(db, now=current)
    promotions_task = promotions_today(db, now=current)

    (
        capstone,
        focus,
        due_count,
        readiness,
        wins,
        events,
        peers,
        promos,
    ) = await asyncio.gather(
        capstone_task,
        focus_task,
        due_task,
        readiness_task,
        micro_wins_task,
        cohort_task,
        peers_task,
        promotions_task,
    )

    return TodaySummaryResponse(
        user=TodayUser(first_name=_first_name(user)),
        goal=goal,
        consistency=consistency,
        progress=progress,
        session=session,
        current_focus=focus,
        capstone=capstone,
        next_milestone=_milestone(goal),
        readiness=readiness,
        intention=intention,
        due_card_count=due_count,
        peers_at_level=peers,
        promotions_today=promos,
        micro_wins=[
            TodayMicroWin(
                kind=w.kind, label=w.label, occurred_at=w.occurred_at
            )
            for w in wins
        ],
        cohort_events=[
            TodayCohortEvent(
                kind=e.kind,
                actor_handle=e.actor_handle,
                label=e.label,
                occurred_at=e.occurred_at,
            )
            for e in events
        ],
    )


__all__ = [
    "build_today_summary",
    "DEFAULT_LEVEL_SLUG",
    "_first_name",
]
