"""F1 — Student risk scoring + slip-pattern classification.

The brain of the retention engine. For every active user, computes:
  - slip_type: which of the 6 slip patterns (or `none`) describes their state
  - risk_score: 0-100 composite, where 0 = healthy and 100 = will-churn-tomorrow
  - days_since_last_session: int or None (never logged in)
  - max_streak_ever: int
  - paid: bool — denormalized for fast filtering
  - recommended_intervention: template_key the F5 outreach service will use
  - risk_reason: human-readable short explanation for the admin UI

The 6 slip patterns (matches docs/RETENTION-ENGINE.md):

  cold_signup        — registered, never returned past day 1
  unpaid_stalled     — first session done, >7d, no payment
  streak_broken      — had >=3 day streak, now silent >=5d
  paid_silent        — paid <30d ago, last session >7d ago
  capstone_stalled   — capstone started, no draft in 14d
  promotion_avoidant — passed senior review, not claiming promotion >7d

Classification priority (when multiple patterns match):
  1. paid_silent          — refund risk = highest urgency
  2. capstone_stalled     — confidence churn near payoff
  3. streak_broken        — most recoverable
  4. promotion_avoidant   — easy wins
  5. unpaid_stalled       — deferred upsell
  6. cold_signup          — bigger volume but lower per-student value

Risk scoring: each detected pattern contributes a base score; the
total is clamped to 0-100. Higher = more urgent. The score is
deliberately interpretable (you can read "85 = paid + silent 12 days")
rather than ML-magic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise_submission import ExerciseSubmission
from app.models.learning_session import LearningSession
from app.models.student_risk_signals import StudentRiskSignals
from app.models.user import User

log = structlog.get_logger()

SlipType = Literal[
    "none",
    "cold_signup",
    "unpaid_stalled",
    "streak_broken",
    "paid_silent",
    "capstone_stalled",
    "promotion_avoidant",
]

# ---------------------------------------------------------------------------
# Tunables — exposed at module level so an ops review can adjust without
# editing scattered constants. Calibrated for early-stage where 5-day
# inactivity matters more than at scale.
# ---------------------------------------------------------------------------

COLD_SIGNUP_THRESHOLD_DAYS = 1
UNPAID_STALLED_THRESHOLD_DAYS = 7
STREAK_RECOVERED_MIN_LENGTH = 3
STREAK_BROKEN_THRESHOLD_DAYS = 5
PAID_SILENT_THRESHOLD_DAYS = 7
PAID_RECENT_WINDOW_DAYS = 30
CAPSTONE_STALLED_THRESHOLD_DAYS = 14
PROMOTION_STALLED_THRESHOLD_DAYS = 7

# Score contributions per slip type. Tuned so the priority order
# (paid_silent > capstone_stalled > ...) shows up in score-desc sorts.
SCORE_BASE = {
    "paid_silent": 80,
    "capstone_stalled": 70,
    "streak_broken": 55,
    "promotion_avoidant": 45,
    "unpaid_stalled": 35,
    "cold_signup": 25,
    "none": 0,
}

# Recommended interventions per slip type. F5 + F6 use these as the
# template_key. A None recommendation means "monitor only — don't
# auto-outreach."
INTERVENTION = {
    "paid_silent": "paid_silent_day_3",
    "capstone_stalled": "capstone_stalled_day_7",
    "streak_broken": "streak_broken_day_5",
    "promotion_avoidant": "promotion_avoidant_day_3",
    "unpaid_stalled": "unpaid_stalled_day_7",
    "cold_signup": "cold_signup_day_1",
    "none": None,
}


@dataclass(frozen=True)
class RiskSignal:
    """In-memory result before persisting to student_risk_signals."""

    user_id: uuid.UUID
    risk_score: int
    slip_type: SlipType
    days_since_last_session: int | None
    max_streak_ever: int
    paid: bool
    recommended_intervention: str | None
    risk_reason: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _days_between(later: datetime | None, earlier: datetime | None) -> int | None:
    if later is None or earlier is None:
        return None
    # Normalize to UTC-aware so naive timestamps from SQLite test fixtures
    # don't blow up the subtraction.
    if later.tzinfo is None:
        later = later.replace(tzinfo=UTC)
    if earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=UTC)
    return (later - earlier).days


# ---------------------------------------------------------------------------
# Per-user signal collection
# ---------------------------------------------------------------------------


@dataclass
class _UserState:
    """Everything we need from the DB to classify one user."""

    user: User
    last_session_at: datetime | None
    sessions_count: int
    max_streak: int  # consecutive days with at least one session
    paid_at: datetime | None
    capstone_started_at: datetime | None
    last_capstone_draft_at: datetime | None
    last_review_passed_at: datetime | None
    last_promotion_attempt_at: datetime | None


async def _collect_user_state(db: AsyncSession, user: User) -> _UserState:
    """Single-user query bundle — 4 small queries instead of 1 megajoin.

    The nightly task runs this for every user, so each query is cheap
    and indexed. Megajoin would be O(users × sessions × submissions);
    splitting keeps each pass O(rows-per-user) which is what indexes
    were designed for.
    """
    # Sessions: most-recent-first, with count.
    sess_q = await db.execute(
        select(
            func.max(LearningSession.started_at),
            func.count(LearningSession.id),
        ).where(LearningSession.user_id == user.id)
    )
    last_session_at, sessions_count = sess_q.one()

    # Capstone signals: ExerciseSubmission rows where the underlying
    # exercise was a capstone. We don't yet have a typed `is_capstone`
    # filter on submission, so for v1 we approximate via "any
    # submission" and refine in F1-followup if needed. The risk service
    # output is documented as v1 — improving the signal is in scope of
    # later tickets.
    sub_q = await db.execute(
        select(
            func.min(ExerciseSubmission.created_at),
            func.max(ExerciseSubmission.created_at),
        ).where(ExerciseSubmission.student_id == user.id)
    )
    capstone_started_at, last_capstone_draft_at = sub_q.one()

    # Streak: a "streak day" is a calendar day with at least one
    # learning_session row. We compute longest-ever from raw started_at
    # values. For v1 this is approximate (timezone-naive at the day
    # boundary); a precise streak service is its own feature.
    days_q = await db.execute(
        select(func.distinct(func.date(LearningSession.started_at)))
        .where(LearningSession.user_id == user.id)
        .order_by(func.date(LearningSession.started_at))
    )
    distinct_days = sorted(d[0] for d in days_q.all() if d[0] is not None)
    max_streak = _longest_consecutive_run(distinct_days)

    # Payment: derived from User.is_active + any enrollment with a
    # payment. Schema varies; for v1 we treat "any past enrollment"
    # as paid. F1-followup tightens this once payments_v2 schema is
    # stable.
    paid_at = None  # placeholder — F1.1 wires this in once we settle on the canonical "is paid" signal.

    return _UserState(
        user=user,
        last_session_at=last_session_at,
        sessions_count=sessions_count,
        max_streak=max_streak,
        paid_at=paid_at,
        capstone_started_at=capstone_started_at,
        last_capstone_draft_at=last_capstone_draft_at,
        last_review_passed_at=None,  # F1.1 — wires from ai_reviews.passed_at
        last_promotion_attempt_at=None,  # F1.1 — wires from cohort_events
    )


def _longest_consecutive_run(days: list) -> int:
    """Given a sorted list of date objects, find the longest run of
    consecutive calendar days. `days` is unique."""
    if not days:
        return 0
    longest = 1
    current = 1
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(state: _UserState, now: datetime | None = None) -> RiskSignal:
    """Pure function — given a user's state, return their RiskSignal.

    Pure so it can be unit-tested without a DB. The async DB collection
    is _collect_user_state; this is the policy.
    """
    n = now or _now()
    days_since_signup = _days_between(n, state.user.created_at)
    days_since_last_session = _days_between(n, state.last_session_at)
    days_since_paid = _days_between(n, state.paid_at)
    days_since_capstone_draft = _days_between(n, state.last_capstone_draft_at)
    days_since_review_passed = _days_between(n, state.last_review_passed_at)
    days_since_promotion_attempt = _days_between(n, state.last_promotion_attempt_at)

    paid = state.paid_at is not None

    # Apply patterns in priority order. First-match wins.
    slip: SlipType = "none"
    reason: str | None = None

    # 1. paid_silent — paid recently AND silent past threshold
    if (
        paid
        and days_since_paid is not None
        and days_since_paid <= PAID_RECENT_WINDOW_DAYS
        and days_since_last_session is not None
        and days_since_last_session >= PAID_SILENT_THRESHOLD_DAYS
    ):
        slip = "paid_silent"
        reason = (
            f"Paid {days_since_paid}d ago · silent for {days_since_last_session}d"
        )

    # 2. capstone_stalled — capstone work started, no draft in threshold
    elif (
        state.capstone_started_at is not None
        and days_since_capstone_draft is not None
        and days_since_capstone_draft >= CAPSTONE_STALLED_THRESHOLD_DAYS
    ):
        slip = "capstone_stalled"
        reason = (
            f"Capstone draft {days_since_capstone_draft}d ago — confidence wall?"
        )

    # 3. streak_broken — had a real habit, life pulled them away
    elif (
        state.max_streak >= STREAK_RECOVERED_MIN_LENGTH
        and days_since_last_session is not None
        and days_since_last_session >= STREAK_BROKEN_THRESHOLD_DAYS
    ):
        slip = "streak_broken"
        reason = (
            f"Had a {state.max_streak}-day streak · silent {days_since_last_session}d"
        )

    # 4. promotion_avoidant — passed review, hasn't tried to claim
    elif (
        days_since_review_passed is not None
        and days_since_promotion_attempt is None
        and days_since_review_passed >= PROMOTION_STALLED_THRESHOLD_DAYS
    ):
        slip = "promotion_avoidant"
        reason = f"Passed review {days_since_review_passed}d ago · gate unopened"

    # 5. unpaid_stalled — first session done, no payment
    elif (
        not paid
        and state.sessions_count >= 1
        and days_since_last_session is not None
        and days_since_last_session >= UNPAID_STALLED_THRESHOLD_DAYS
    ):
        slip = "unpaid_stalled"
        reason = (
            f"Free tier · {state.sessions_count} sessions · "
            f"silent {days_since_last_session}d"
        )

    # 6. cold_signup — registered, never returned
    elif (
        state.sessions_count == 0
        and days_since_signup is not None
        and days_since_signup >= COLD_SIGNUP_THRESHOLD_DAYS
    ):
        slip = "cold_signup"
        reason = f"Registered {days_since_signup}d ago · no first session"

    # Risk score — base + linear bonus based on staleness.
    # Capped at 100 so admin UI doesn't show 137-out-of-100.
    base = SCORE_BASE[slip]
    bonus = min(20, (days_since_last_session or 0) // 2) if slip != "none" else 0
    risk_score = min(100, base + bonus)

    return RiskSignal(
        user_id=state.user.id,
        risk_score=risk_score,
        slip_type=slip,
        days_since_last_session=days_since_last_session,
        max_streak_ever=state.max_streak,
        paid=paid,
        recommended_intervention=INTERVENTION[slip],
        risk_reason=reason,
    )


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


async def score_user(db: AsyncSession, user: User) -> RiskSignal:
    """Compute one user's signal. Used by tests + ad-hoc invocations."""
    state = await _collect_user_state(db, user)
    return classify(state)


async def score_all_users(db: AsyncSession) -> int:
    """Recompute signals for every active user. Returns count.

    Called by the nightly Celery task. Iterates user-by-user — 4 tiny
    queries each — rather than one megajoin so each user's scoring is
    isolated (a single bad row doesn't take down the whole pass).

    Upserts via ON CONFLICT (user_id) so the table is always one-row-
    per-user and yesterday's signals get overwritten cleanly.
    """
    users_q = await db.execute(
        select(User).where(User.is_active.is_(True))
    )
    users = users_q.scalars().all()

    n = _now()
    written = 0
    for user in users:
        try:
            signal = await score_user(db, user)
        except Exception as exc:
            # Per-user failure is logged + skipped. The next nightly run
            # tries again. Don't take the whole pass down for one bad
            # row.
            log.warning(
                "risk_scoring.user_failed",
                user_id=str(user.id),
                error=str(exc),
            )
            continue

        stmt = pg_insert(StudentRiskSignals).values(
            id=uuid.uuid4(),
            user_id=signal.user_id,
            risk_score=signal.risk_score,
            slip_type=signal.slip_type,
            days_since_last_session=signal.days_since_last_session,
            max_streak_ever=signal.max_streak_ever,
            paid=signal.paid,
            recommended_intervention=signal.recommended_intervention,
            risk_reason=signal.risk_reason,
            computed_at=n,
        )
        # ON CONFLICT user_id DO UPDATE — keeps one row per user.
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "risk_score": signal.risk_score,
                "slip_type": signal.slip_type,
                "days_since_last_session": signal.days_since_last_session,
                "max_streak_ever": signal.max_streak_ever,
                "paid": signal.paid,
                "recommended_intervention": signal.recommended_intervention,
                "risk_reason": signal.risk_reason,
                "computed_at": n,
            },
        )
        await db.execute(stmt)
        written += 1

    await db.commit()
    log.info("risk_scoring.complete", users_scored=written)
    return written


async def list_by_slip_type(
    db: AsyncSession, slip_type: SlipType, limit: int = 20
) -> list[StudentRiskSignals]:
    """Read API for the F4 console panels — pull top-risk students of a
    specific slip pattern. Indexed query (slip_type, risk_score DESC)."""
    q = await db.execute(
        select(StudentRiskSignals)
        .where(StudentRiskSignals.slip_type == slip_type)
        .order_by(StudentRiskSignals.risk_score.desc())
        .limit(limit)
    )
    return list(q.scalars().all())
