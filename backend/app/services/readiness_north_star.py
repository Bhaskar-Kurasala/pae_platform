"""North-star metric instrumentation for the Readiness Diagnostic.

The page's north-star metric:

    % of diagnostic sessions where the suggested next action is
    completed within 24 hours.

This module owns three responsibilities:

  1. **Click beacon** — record_click() sets
     ``readiness_diagnostic_sessions.next_action_clicked_at`` when the
     student clicks the verdict's primary CTA. Idempotent — repeat
     clicks don't reset the timestamp.

  2. **Per-intent completion criteria** — given a session + verdict +
     click timestamp, check_completion() inspects the user's activity
     and decides whether the next action has been "completed" within
     the 24-hour window. Each intent has its own queryable signal —
     see INTENT_CRITERIA below for the full mapping. Idempotent: once
     ``next_action_completed_at`` is set, subsequent calls don't move it.

  3. **Aggregate rate** — compute_north_star_rate() returns the rate
     over a configurable window (default: last 14 days) for the admin
     dashboard.

Completion detection runs lazily — the frontend calls the
check-completion endpoint on Job Readiness page load. This is the
right moment because students who acted on the verdict typically
return to Job Readiness to see the updated picture. A backend cron
fallback can be added later if the lazy path leaves too many sessions
uncounted; for MVP the lazy path is correct and cheap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise_submission import ExerciseSubmission
from app.models.interview_session import InterviewSession
from app.models.jd_decoder import JdMatchScore
from app.models.readiness import (
    DIAGNOSTIC_STATUS_COMPLETED,
    ReadinessDiagnosticSession,
    ReadinessVerdict,
)
from app.models.resume import Resume
from app.models.student_progress import StudentProgress
from app.models.tailored_resume import TailoredResume

log = structlog.get_logger()

# 24-hour completion window — the spec's metric definition.
COMPLETION_WINDOW = timedelta(hours=24)

NextActionIntent = Literal[
    "skills_gap",
    "story_gap",
    "interview_gap",
    "jd_target_unclear",
    "ready_but_stalling",
    "thin_data",
    "ready_to_apply",
]


# ---------------------------------------------------------------------------
# Per-intent completion criteria
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletionCriterion:
    """Describes how an intent's completion is detected.

    The ``description`` field is what surfaces in IMPLEMENTATION_NOTES
    + the analyst dashboard so the metric is auditable: "what does
    'completed' mean for this intent?"
    """

    intent: str
    description: str


# Documented criteria. Keep in lockstep with the per-intent _check_*
# helpers below — every intent here has exactly one helper.
INTENT_CRITERIA: dict[str, CompletionCriterion] = {
    "skills_gap": CompletionCriterion(
        intent="skills_gap",
        description=(
            "A new student_progress row reaches completed_at, OR a new "
            "exercise_submission lands, after the click timestamp."
        ),
    ),
    "story_gap": CompletionCriterion(
        intent="story_gap",
        description=(
            "A TailoredResume is generated for the user after the "
            "click timestamp, OR the BaseResume.updated_at advances "
            "past the click timestamp."
        ),
    ),
    "interview_gap": CompletionCriterion(
        intent="interview_gap",
        description=(
            "A new InterviewSession is created for the user after "
            "the click timestamp."
        ),
    ),
    "jd_target_unclear": CompletionCriterion(
        intent="jd_target_unclear",
        description=(
            "A new JdAnalysis or JdMatchScore is created for the user "
            "after the click timestamp."
        ),
    ),
    "ready_but_stalling": CompletionCriterion(
        intent="ready_but_stalling",
        description=(
            "Either a TailoredResume OR an InterviewSession is created "
            "after the click timestamp. (A direct apply-flow signal "
            "would be ideal but does not exist yet — flagged in "
            "IMPLEMENTATION_NOTES as a Phase 2 instrumentation gap.)"
        ),
    ),
    "thin_data": CompletionCriterion(
        intent="thin_data",
        description=(
            "Any meaningful activity (lesson completion, exercise "
            "submission, mock session, JD decode, or tailored resume) "
            "after the click timestamp. Catch-all because the route "
            "for thin-data verdicts is /today, which fans out to "
            "multiple surfaces."
        ),
    ),
    "ready_to_apply": CompletionCriterion(
        intent="ready_to_apply",
        description=(
            "A TailoredResume is generated after the click timestamp "
            "(proxy for the apply flow). Same Phase 2 gap as "
            "ready_but_stalling — direct apply telemetry is missing."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Click beacon
# ---------------------------------------------------------------------------


class SessionMissingVerdictError(RuntimeError):
    pass


async def record_click(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> datetime:
    """Stamp ``next_action_clicked_at`` on the session. Idempotent: a
    repeat click does not move the timestamp.

    Raises SessionMissingVerdictError if the session has no verdict —
    the click beacon should only fire AFTER finalize_session set the
    verdict. Defensive — protects analytics from clicks against
    abandoned/active sessions.
    """
    row = (
        await db.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == session_id,
                ReadinessDiagnosticSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise SessionMissingVerdictError(
            f"diagnostic session {session_id} not found for this user"
        )
    if row.verdict_id is None:
        raise SessionMissingVerdictError(
            f"diagnostic session {session_id} has no verdict to click"
        )

    if row.next_action_clicked_at is not None:
        # Idempotent — return the existing timestamp.
        return row.next_action_clicked_at

    now = datetime.now(UTC)
    row.next_action_clicked_at = now
    await db.commit()
    log.info(
        "readiness_north_star.click_recorded",
        user_id=str(user_id),
        session_id=str(session_id),
    )
    return now


# ---------------------------------------------------------------------------
# Completion check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletionCheckResult:
    session_id: uuid.UUID
    clicked_at: datetime | None
    completed_at: datetime | None
    completed_within_window: bool
    intent: str | None


async def check_completion(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> CompletionCheckResult:
    """Inspect activity since the click and stamp
    ``next_action_completed_at`` if the per-intent criterion is met
    within the 24-hour window.

    Idempotent: once completed_at is set, subsequent calls return the
    same value without re-running the criterion. Non-clicked sessions
    short-circuit immediately — there's nothing to compare against.
    """
    row = (
        await db.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == session_id,
                ReadinessDiagnosticSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise SessionMissingVerdictError(
            f"diagnostic session {session_id} not found for this user"
        )
    if row.verdict_id is None:
        return CompletionCheckResult(
            session_id=session_id,
            clicked_at=None,
            completed_at=None,
            completed_within_window=False,
            intent=None,
        )

    verdict = (
        await db.execute(
            select(ReadinessVerdict).where(ReadinessVerdict.id == row.verdict_id)
        )
    ).scalar_one_or_none()
    intent = verdict.next_action_intent if verdict else None

    clicked = _ensure_aware(row.next_action_clicked_at)
    completed = _ensure_aware(row.next_action_completed_at)

    if clicked is None:
        return CompletionCheckResult(
            session_id=session_id,
            clicked_at=None,
            completed_at=None,
            completed_within_window=False,
            intent=intent,
        )

    if completed is not None:
        # Already stamped — idempotent return.
        return CompletionCheckResult(
            session_id=session_id,
            clicked_at=clicked,
            completed_at=completed,
            completed_within_window=(completed - clicked) <= COMPLETION_WINDOW,
            intent=intent,
        )

    # Run the per-intent criterion. Each helper returns the first
    # qualifying activity timestamp (UTC-aware) or None.
    activity_at = await _detect_completion(
        db,
        user_id=user_id,
        intent=intent,
        clicked_at=clicked,
    )
    if activity_at is None:
        return CompletionCheckResult(
            session_id=session_id,
            clicked_at=clicked,
            completed_at=None,
            completed_within_window=False,
            intent=intent,
        )

    # Stamp regardless of whether it lands inside the 24h window — the
    # field records WHEN they completed; the metric query separately
    # filters by the window. This way late completions (>24h) are
    # still queryable for funnel analysis.
    row.next_action_completed_at = activity_at
    await db.commit()
    log.info(
        "readiness_north_star.completion_recorded",
        user_id=str(user_id),
        session_id=str(session_id),
        intent=intent,
        within_window=(activity_at - clicked) <= COMPLETION_WINDOW,
    )
    return CompletionCheckResult(
        session_id=session_id,
        clicked_at=clicked,
        completed_at=activity_at,
        completed_within_window=(activity_at - clicked) <= COMPLETION_WINDOW,
        intent=intent,
    )


async def _detect_completion(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    intent: str | None,
    clicked_at: datetime,
) -> datetime | None:
    """Dispatch to per-intent helpers. Unknown intent → None."""
    if intent in (None, "skills_gap"):
        # Safe default — skills_gap is the most common verdict; if intent
        # is unset we fall back to "any meaningful platform activity."
        return await _earliest_lesson_or_exercise_after(
            db, user_id=user_id, after=clicked_at
        )
    if intent == "story_gap":
        return await _earliest_story_signal_after(
            db, user_id=user_id, after=clicked_at
        )
    if intent == "interview_gap":
        return await _earliest_interview_after(
            db, user_id=user_id, after=clicked_at
        )
    if intent == "jd_target_unclear":
        return await _earliest_jd_signal_after(
            db, user_id=user_id, after=clicked_at
        )
    if intent in ("ready_but_stalling", "ready_to_apply"):
        # Apply-flow signal doesn't exist yet (Phase 2 instrumentation
        # gap); fall back to story OR interview signals, the closest
        # proxies for "took action toward applying".
        story = await _earliest_story_signal_after(
            db, user_id=user_id, after=clicked_at
        )
        interview = await _earliest_interview_after(
            db, user_id=user_id, after=clicked_at
        )
        return _earliest(story, interview)
    if intent == "thin_data":
        return await _earliest_any_activity_after(
            db, user_id=user_id, after=clicked_at
        )
    return None


# ---------------------------------------------------------------------------
# Per-intent helpers
# ---------------------------------------------------------------------------


async def _earliest_lesson_or_exercise_after(
    db: AsyncSession, *, user_id: uuid.UUID, after: datetime
) -> datetime | None:
    lesson = (
        await db.execute(
            select(func.min(StudentProgress.completed_at)).where(
                StudentProgress.student_id == user_id,
                StudentProgress.completed_at.is_not(None),
                StudentProgress.completed_at > after,
            )
        )
    ).scalar_one_or_none()
    exercise = (
        await db.execute(
            select(func.min(ExerciseSubmission.created_at)).where(
                ExerciseSubmission.student_id == user_id,
                ExerciseSubmission.created_at > after,
            )
        )
    ).scalar_one_or_none()
    return _earliest(_ensure_aware(lesson), _ensure_aware(exercise))


async def _earliest_story_signal_after(
    db: AsyncSession, *, user_id: uuid.UUID, after: datetime
) -> datetime | None:
    tailored = (
        await db.execute(
            select(func.min(TailoredResume.created_at)).where(
                TailoredResume.user_id == user_id,
                TailoredResume.created_at > after,
            )
        )
    ).scalar_one_or_none()
    resume_bumped = (
        await db.execute(
            select(func.min(Resume.updated_at)).where(
                Resume.user_id == user_id,
                Resume.updated_at > after,
            )
        )
    ).scalar_one_or_none()
    return _earliest(_ensure_aware(tailored), _ensure_aware(resume_bumped))


async def _earliest_interview_after(
    db: AsyncSession, *, user_id: uuid.UUID, after: datetime
) -> datetime | None:
    row = (
        await db.execute(
            select(func.min(InterviewSession.created_at)).where(
                InterviewSession.user_id == user_id,
                InterviewSession.created_at > after,
            )
        )
    ).scalar_one_or_none()
    return _ensure_aware(row)


async def _earliest_jd_signal_after(
    db: AsyncSession, *, user_id: uuid.UUID, after: datetime
) -> datetime | None:
    # JdMatchScore is per-student so user_id filter applies.
    score = (
        await db.execute(
            select(func.min(JdMatchScore.created_at)).where(
                JdMatchScore.user_id == user_id,
                JdMatchScore.created_at > after,
            )
        )
    ).scalar_one_or_none()
    # JdAnalysis is universal (no user_id) — but a user-driven decode
    # always writes a per-student JdMatchScore at the same time, so the
    # match-score signal is sufficient.
    return _ensure_aware(score)


async def _earliest_any_activity_after(
    db: AsyncSession, *, user_id: uuid.UUID, after: datetime
) -> datetime | None:
    """Catch-all for thin_data — any meaningful activity counts."""
    candidates = await _gather_all_signals(
        db, user_id=user_id, after=after
    )
    valid = [c for c in candidates if c is not None]
    if not valid:
        return None
    return min(valid)


async def _gather_all_signals(
    db: AsyncSession, *, user_id: uuid.UUID, after: datetime
) -> list[datetime | None]:
    return [
        await _earliest_lesson_or_exercise_after(
            db, user_id=user_id, after=after
        ),
        await _earliest_story_signal_after(
            db, user_id=user_id, after=after
        ),
        await _earliest_interview_after(
            db, user_id=user_id, after=after
        ),
        await _earliest_jd_signal_after(
            db, user_id=user_id, after=after
        ),
    ]


def _earliest(*candidates: datetime | None) -> datetime | None:
    valid = [c for c in candidates if c is not None]
    if not valid:
        return None
    return min(valid)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes for timezone-aware columns;
    Postgres returns aware. Coerce to UTC-aware so comparisons work
    on both."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ---------------------------------------------------------------------------
# Aggregate rate (admin dashboard surface)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NorthStarRate:
    window_days: int
    sessions_with_verdict: int
    sessions_clicked: int
    sessions_completed_within_24h: int
    click_through_rate: float
    completion_within_24h_rate: float


async def compute_north_star_rate(
    db: AsyncSession,
    *,
    window_days: int = 14,
    now: datetime | None = None,
) -> NorthStarRate:
    """Compute the page's north-star rate over the last ``window_days``.

    Two rates surface separately so the funnel break (if any) is
    identifiable:

      * click_through_rate = clicked / has_verdict
      * completion_within_24h_rate = completed_within_24h / clicked

    The product north-star is the second rate, but the first tells us
    whether a low completion rate is an "action wasn't compelling" or
    "the recommended action wasn't completable" problem.
    """
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    has_verdict = (
        await db.execute(
            select(func.count(ReadinessDiagnosticSession.id)).where(
                ReadinessDiagnosticSession.status == DIAGNOSTIC_STATUS_COMPLETED,
                ReadinessDiagnosticSession.completed_at.is_not(None),
                ReadinessDiagnosticSession.completed_at >= window_start,
            )
        )
    ).scalar_one() or 0

    clicked = (
        await db.execute(
            select(func.count(ReadinessDiagnosticSession.id)).where(
                ReadinessDiagnosticSession.status == DIAGNOSTIC_STATUS_COMPLETED,
                ReadinessDiagnosticSession.completed_at.is_not(None),
                ReadinessDiagnosticSession.completed_at >= window_start,
                ReadinessDiagnosticSession.next_action_clicked_at.is_not(None),
            )
        )
    ).scalar_one() or 0

    # Completed within 24h of click. We use a SQL-level interval
    # comparison so it works on both SQLite and Postgres without
    # pulling rows into Python.
    completed_24h = (
        await db.execute(
            select(func.count(ReadinessDiagnosticSession.id)).where(
                and_(
                    ReadinessDiagnosticSession.status
                    == DIAGNOSTIC_STATUS_COMPLETED,
                    ReadinessDiagnosticSession.completed_at.is_not(None),
                    ReadinessDiagnosticSession.completed_at >= window_start,
                    ReadinessDiagnosticSession.next_action_clicked_at.is_not(None),
                    ReadinessDiagnosticSession.next_action_completed_at.is_not(None),
                    # within_window = (completed - clicked) <= 24h
                    # Expressed via direct comparison: completed_at <=
                    # clicked_at + 24h. Using sqlalchemy's func.datetime
                    # would diverge between dialects, so we filter in
                    # Python instead.
                )
            )
        )
    ).scalar_one() or 0

    # Now refine completed_24h by pulling the candidate rows and
    # filtering in Python — small N (the count above caps it).
    if completed_24h:
        rows = (
            await db.execute(
                select(
                    ReadinessDiagnosticSession.next_action_clicked_at,
                    ReadinessDiagnosticSession.next_action_completed_at,
                ).where(
                    ReadinessDiagnosticSession.status
                    == DIAGNOSTIC_STATUS_COMPLETED,
                    ReadinessDiagnosticSession.completed_at >= window_start,
                    ReadinessDiagnosticSession.next_action_clicked_at.is_not(
                        None
                    ),
                    ReadinessDiagnosticSession.next_action_completed_at.is_not(
                        None
                    ),
                )
            )
        ).all()
        in_window = 0
        for clicked_at, completed_at in rows:
            # The WHERE clause filters out NULLs but mypy doesn't narrow.
            aware_clicked = _ensure_aware(clicked_at)
            aware_completed = _ensure_aware(completed_at)
            if aware_clicked is None or aware_completed is None:
                continue
            if (aware_completed - aware_clicked) <= COMPLETION_WINDOW:
                in_window += 1
        completed_24h = in_window

    click_through = (
        clicked / has_verdict if has_verdict else 0.0
    )
    completion = (
        completed_24h / clicked if clicked else 0.0
    )
    return NorthStarRate(
        window_days=window_days,
        sessions_with_verdict=int(has_verdict),
        sessions_clicked=int(clicked),
        sessions_completed_within_24h=int(completed_24h),
        click_through_rate=round(click_through, 4),
        completion_within_24h_rate=round(completion, 4),
    )


__all__ = [
    "COMPLETION_WINDOW",
    "CompletionCheckResult",
    "INTENT_CRITERIA",
    "NorthStarRate",
    "SessionMissingVerdictError",
    "check_completion",
    "compute_north_star_rate",
    "record_click",
]
