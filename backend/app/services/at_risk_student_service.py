"""At-risk student service (P2-14).

Surfaces enrolled students likely to disengage so an admin can reach out before
the churn happens. Deterministic (no LLM) — built from signals already in the
database.

Signals (all weighted):
- `no_login_days`  — days since `users.last_login_at`. Silence is the loudest
  signal of churn.
- `lesson_stall_days` — days since their most recent `student_progress` row
  with status="completed". Distinguishes "logs in but coasts" from real learning.
- `help_drought` — ratio of help-agent invocations in the *prior* window versus
  the *recent* window. A student who used to ask questions and stopped is more
  worrying than one who never asked at all.
- `low_mood_streak` — count of recent reflections with mood in the low bucket
  (`stuck`, `overwhelmed`, `frustrated`). Self-reported affect, so high signal.
- `progress_pct_stall` — students with active enrollments but `progress_pct`
  far below what their tenure would predict.

Each surfaced student gets a score (0.0–1.0) and a short list of human-readable
`reasons` — typically the 1-2 dominant factors. The admin should see *why* at a
glance, not a black-box ranking.

Pure helpers live at the top for unit testability without a DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction
from app.models.enrollment import Enrollment
from app.models.reflection import Reflection
from app.models.student_progress import StudentProgress
from app.models.user import User

log = structlog.get_logger()


# Moods that count as "student is struggling" in reflections. Everything else
# (calm, energised, proud, neutral) doesn't contribute to the low_mood signal.
LOW_MOODS: frozenset[str] = frozenset({"stuck", "overwhelmed", "frustrated", "exhausted"})


# Help-oriented agents — same list as the confusion heatmap. Keep in sync.
# D11 cutover (Checkpoint 4) absorbed coding_assistant + code_review
# into senior_engineer (Pass 3c E2). The 0059 data migration
# consolidates historical agent_actions rows so this query matches
# pre-cutover activity too.
HELP_AGENTS: tuple[str, ...] = (
    "socratic_tutor",
    "senior_engineer",
    "student_buddy",
    "project_evaluator",
)


# Minimum tenure (days) before we'll flag someone for progress_pct stall.
# Too soon and we're just flagging "new student hasn't caught up yet", which
# is noise an admin can't act on.
MIN_TENURE_DAYS_FOR_STALL = 14


@dataclass(frozen=True)
class Signal:
    """One risk factor with a numeric contribution and a human reason.

    `weight` is the fraction of the total risk score this signal contributes
    (0.0–1.0). `reason` is a short sentence an admin can read and immediately
    know what to do about.
    """

    name: str
    weight: float
    reason: str


@dataclass(frozen=True)
class AtRiskStudent:
    student_id: str
    email: str
    full_name: str
    risk_score: float                    # 0.0–1.0, higher = more at risk
    reasons: list[str]                   # 1-3 dominant signals, already phrased
    no_login_days: int | None            # None if never logged in
    lesson_stall_days: int | None        # None if never completed a lesson
    help_requests_recent: int
    help_requests_prior: int
    low_mood_count: int
    progress_pct: float                  # avg across active enrollments
    signals: list[Signal] = field(default_factory=list)


# ── Pure scoring helpers ──────────────────────────────────────────────────────


def login_silence_signal(
    last_login_at: datetime | None,
    created_at: datetime,
    *,
    now: datetime,
) -> Signal | None:
    """Flag students who have gone quiet.

    Never-logged-in is only a signal if they've been on the roll >7 days.
    Logged-in students are scored on a 0–30 day ramp.
    """
    if last_login_at is None:
        days_since_signup = max(0, (now - created_at).days)
        if days_since_signup < 7:
            return None
        weight = min(1.0, days_since_signup / 21.0)
        return Signal(
            name="no_login",
            weight=weight,
            reason=f"Never logged in — {days_since_signup} days since signup",
        )

    if last_login_at.tzinfo is None:
        last_login_at = last_login_at.replace(tzinfo=UTC)
    days = max(0, (now - last_login_at).days)
    if days < 5:
        return None
    weight = min(1.0, (days - 5) / 25.0 + 0.1)
    unit = "day" if days == 1 else "days"
    return Signal(
        name="no_login",
        weight=weight,
        reason=f"No login in {days} {unit}",
    )


def lesson_stall_signal(
    last_completed_at: datetime | None,
    enrolled_at: datetime | None,
    *,
    now: datetime,
) -> Signal | None:
    """Flag students who log in but aren't completing lessons.

    Never-completed is only a signal for students enrolled >14 days. Otherwise
    it's just a new enrollment that hasn't got going yet.
    """
    if last_completed_at is None:
        if enrolled_at is None:
            return None
        if enrolled_at.tzinfo is None:
            enrolled_at = enrolled_at.replace(tzinfo=UTC)
        tenure = max(0, (now - enrolled_at).days)
        if tenure < MIN_TENURE_DAYS_FOR_STALL:
            return None
        weight = min(0.8, tenure / 60.0 + 0.3)
        return Signal(
            name="lesson_stall",
            weight=weight,
            reason=f"No lesson completed in {tenure} days since enrolling",
        )

    if last_completed_at.tzinfo is None:
        last_completed_at = last_completed_at.replace(tzinfo=UTC)
    days = max(0, (now - last_completed_at).days)
    if days < 10:
        return None
    weight = min(0.9, (days - 10) / 30.0 + 0.2)
    return Signal(
        name="lesson_stall",
        weight=weight,
        reason=f"No lesson completed in {days} days",
    )


def help_drought_signal(
    recent_count: int,
    prior_count: int,
) -> Signal | None:
    """Flag students whose help-seeking dropped off a cliff.

    A student who used to ask questions and stopped is more at risk than one
    who never asked. Only fires when prior > recent AND prior was meaningful
    (≥3), so we don't flag every single fluctuation.
    """
    if prior_count < 3:
        return None
    if recent_count >= prior_count:
        return None
    drop_ratio = 1.0 - (recent_count / prior_count)
    if drop_ratio < 0.5:
        return None
    weight = min(0.7, drop_ratio * 0.8)
    return Signal(
        name="help_drought",
        weight=weight,
        reason=f"Help-seeking dropped from {prior_count} to {recent_count} this window",
    )


def low_mood_signal(low_mood_count: int, total_reflections: int) -> Signal | None:
    """Flag students reporting low mood in recent reflections.

    Uses an absolute count (≥2 struggle-moods) AND a ratio check so a student
    with one bad day doesn't get flagged.
    """
    if low_mood_count < 2:
        return None
    if total_reflections == 0:
        return None
    ratio = low_mood_count / total_reflections
    if ratio < 0.4:
        return None
    weight = min(0.9, 0.4 + (ratio - 0.4) * 1.2)
    return Signal(
        name="low_mood",
        weight=weight,
        reason=f"{low_mood_count} of last {total_reflections} reflections flagged struggling mood",
    )


def progress_stall_signal(
    avg_progress_pct: float,
    tenure_days: int,
) -> Signal | None:
    """Flag students with low progress_pct relative to how long they've had.

    Linear expectation: after 30 days you should be ~30% through. More lenient
    than that — we flag only when progress is <half of the naive expectation.
    """
    if tenure_days < MIN_TENURE_DAYS_FOR_STALL:
        return None
    expected = min(100.0, tenure_days * (100.0 / 90.0))  # full curriculum ~90 days
    if avg_progress_pct >= expected * 0.5:
        return None
    shortfall = (expected * 0.5) - avg_progress_pct
    weight = min(0.6, shortfall / 40.0)
    if weight < 0.1:
        return None
    return Signal(
        name="progress_stall",
        weight=weight,
        reason=(
            f"Only {avg_progress_pct:.0f}% through after {tenure_days} days "
            f"(expected ~{int(expected * 0.5)}%)"
        ),
    )


def combine_signals(signals: list[Signal]) -> tuple[float, list[str]]:
    """Fold a list of signals into a 0.0–1.0 risk score + top reasons.

    We cap at 1.0. Multiple signals compound (soft-OR) rather than average,
    because a student hitting both "no login" AND "low mood" is categorically
    worse off than a student hitting one — we don't want averaging to dilute it.
    """
    if not signals:
        return 0.0, []
    # Soft-OR: 1 - product(1 - w)
    product = 1.0
    for s in signals:
        product *= 1.0 - max(0.0, min(1.0, s.weight))
    score = 1.0 - product
    # Sort signals by weight desc; take top 3 reasons.
    top = sorted(signals, key=lambda s: s.weight, reverse=True)[:3]
    return round(score, 3), [s.reason for s in top]


def score_student(
    *,
    last_login_at: datetime | None,
    created_at: datetime,
    last_completed_at: datetime | None,
    earliest_enrolled_at: datetime | None,
    help_recent: int,
    help_prior: int,
    low_mood_count: int,
    total_reflections: int,
    avg_progress_pct: float,
    tenure_days: int,
    now: datetime,
) -> tuple[float, list[str], list[Signal]]:
    """Run all signals and fold into a final (score, reasons, signals) triple."""
    signals: list[Signal] = []
    for sig in (
        login_silence_signal(last_login_at, created_at, now=now),
        lesson_stall_signal(last_completed_at, earliest_enrolled_at, now=now),
        help_drought_signal(help_recent, help_prior),
        low_mood_signal(low_mood_count, total_reflections),
        progress_stall_signal(avg_progress_pct, tenure_days),
    ):
        if sig is not None:
            signals.append(sig)
    score, reasons = combine_signals(signals)
    return score, reasons, signals


# ── DB-backed computation ────────────────────────────────────────────────────


async def compute_at_risk_students(
    db: AsyncSession,
    *,
    limit: int = 25,
    min_score: float = 0.35,
    recent_window_days: int = 14,
    prior_window_days: int = 28,
    reflection_window_days: int = 21,
    now: datetime | None = None,
) -> list[AtRiskStudent]:
    """Rank students most likely to churn, with human-readable reasons.

    - `recent_window_days`: the window we're measuring "is this student OK right
      now" against (default 2 weeks).
    - `prior_window_days`: the window just before, used to detect drop-offs
      (default 4 weeks prior, non-overlapping).
    - `min_score`: students below this are filtered out — admins want
      actionable names, not a full leaderboard.
    """
    current = now or datetime.now(UTC)
    recent_start = current - timedelta(days=recent_window_days)
    prior_start = current - timedelta(days=recent_window_days + prior_window_days)
    reflection_start = (current - timedelta(days=reflection_window_days)).date()

    # Pull all active students. We'll compute signals per student in Python —
    # this is O(students × ~5 queries) which is fine for admin-sized rosters.
    students_result = await db.execute(
        select(User).where(
            User.role == "student",
            User.is_deleted.is_(False),
            User.is_active.is_(True),
        )
    )
    students = list(students_result.scalars().all())

    out: list[AtRiskStudent] = []
    for student in students:
        last_completed_at = (
            await db.execute(
                select(func.max(StudentProgress.completed_at)).where(
                    StudentProgress.student_id == student.id,
                    StudentProgress.status == "completed",
                )
            )
        ).scalar_one_or_none()

        earliest_enrolled_at = (
            await db.execute(
                select(func.min(Enrollment.enrolled_at)).where(
                    Enrollment.student_id == student.id,
                )
            )
        ).scalar_one_or_none()

        help_recent = (
            await db.execute(
                select(func.count(AgentAction.id)).where(
                    AgentAction.student_id == student.id,
                    AgentAction.agent_name.in_(HELP_AGENTS),
                    AgentAction.created_at >= recent_start,
                )
            )
        ).scalar_one()

        help_prior = (
            await db.execute(
                select(func.count(AgentAction.id)).where(
                    AgentAction.student_id == student.id,
                    AgentAction.agent_name.in_(HELP_AGENTS),
                    AgentAction.created_at >= prior_start,
                    AgentAction.created_at < recent_start,
                )
            )
        ).scalar_one()

        reflections_rows = (
            await db.execute(
                select(Reflection.mood).where(
                    Reflection.user_id == student.id,
                    Reflection.reflection_date >= reflection_start,
                )
            )
        ).scalars().all()
        total_reflections = len(reflections_rows)
        low_mood_count = sum(1 for m in reflections_rows if m in LOW_MOODS)

        avg_progress_row = (
            await db.execute(
                select(func.avg(Enrollment.progress_pct)).where(
                    Enrollment.student_id == student.id,
                    Enrollment.status == "active",
                )
            )
        ).scalar_one_or_none()
        avg_progress_pct = float(avg_progress_row) if avg_progress_row is not None else 0.0

        created_at = student.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        tenure_days = max(0, (current - created_at).days)

        score, reasons, signals = score_student(
            last_login_at=student.last_login_at,
            created_at=created_at,
            last_completed_at=last_completed_at,
            earliest_enrolled_at=earliest_enrolled_at,
            help_recent=help_recent,
            help_prior=help_prior,
            low_mood_count=low_mood_count,
            total_reflections=total_reflections,
            avg_progress_pct=avg_progress_pct,
            tenure_days=tenure_days,
            now=current,
        )
        if score < min_score:
            continue

        no_login_days: int | None
        if student.last_login_at is None:
            no_login_days = None
        else:
            last_login = student.last_login_at
            if last_login.tzinfo is None:
                last_login = last_login.replace(tzinfo=UTC)
            no_login_days = max(0, (current - last_login).days)

        lesson_stall_days: int | None
        if last_completed_at is None:
            lesson_stall_days = None
        else:
            lc = last_completed_at
            if lc.tzinfo is None:
                lc = lc.replace(tzinfo=UTC)
            lesson_stall_days = max(0, (current - lc).days)

        out.append(
            AtRiskStudent(
                student_id=str(student.id),
                email=student.email,
                full_name=student.full_name,
                risk_score=score,
                reasons=reasons,
                no_login_days=no_login_days,
                lesson_stall_days=lesson_stall_days,
                help_requests_recent=help_recent,
                help_requests_prior=help_prior,
                low_mood_count=low_mood_count,
                progress_pct=round(avg_progress_pct, 1),
                signals=signals,
            )
        )

    out.sort(key=lambda s: s.risk_score, reverse=True)
    log.info(
        "at_risk.computed",
        students_scanned=len(students),
        at_risk=len(out),
        threshold=min_score,
    )
    return out[:limit]
