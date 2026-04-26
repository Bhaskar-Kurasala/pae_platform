"""Readiness Overview aggregator.

Replaces the Job Readiness Overview view's hard-coded KPI block with
a single signal-driven payload. Composes:

  * Skill score from `student_progress` (lessons completed / total).
  * Proof score from capstone drafts + AI reviews + autopsies.
  * Interview score from the last 3 mock-session verdict labels.
  * Targeting score from saved JDs + best fit + target_role presence.
  * Weekly north-star delta (reuses `compute_north_star_rate`).
  * Top-3 actions ranked from real signals (weakness ledger, JD count,
    resume freshness, autopsy recency, latest verdict route).

Pure helpers (clamp + score math + action ranker) live up top so they
can be unit-tested without a DB. The async `load_overview` orchestrates
the cheap queries with `asyncio.gather`.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_review import AIReview
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.goal_contract import GoalContract
from app.models.interview_session import InterviewSession
from app.models.jd_library import JdLibrary
from app.models.lesson import Lesson
from app.models.mock_interview import MockSessionReport, MockWeaknessLedger
from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.models.readiness import (
    DIAGNOSTIC_STATUS_COMPLETED,
    ReadinessDiagnosticSession,
    ReadinessVerdict,
)
from app.models.readiness_action_completion import ReadinessActionCompletion
from app.models.resume import Resume
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.schemas.readiness_overview import (
    LatestVerdict,
    NextAction,
    NorthStarDelta,
    OverviewResponse,
    SubScores,
    TrendPoint,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pure helpers (testable without DB)
# ---------------------------------------------------------------------------


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def compute_core_skill_score(
    lessons_completed_total: int, lessons_total: int
) -> int:
    """Skill score = % of lessons completed, clamped 0..100."""
    pct = (lessons_completed_total / max(1, lessons_total)) * 100
    return _clamp(int(round(pct)))


def compute_proof_score(
    capstone_drafts_count: int,
    ai_reviews_count: int,
    autopsies_count: int,
) -> int:
    """Proof = drafts*30 + reviews*10 + autopsies*15, capped at 100."""
    raw = (
        capstone_drafts_count * 30
        + ai_reviews_count * 10
        + autopsies_count * 15
    )
    return min(100, max(0, raw))


def compute_interview_score(verdicts: list[str]) -> int:
    """Interview score from the last 3 mock-session verdict labels.

    Mapping:
      ready=100, promising=70, not_ready=35, default=50.
    Empty list → 0.
    """
    if not verdicts:
        return 0

    mapping = {"ready": 100, "promising": 70, "not_ready": 35}
    last_three = verdicts[-3:]
    scores = [mapping.get(v, 50) for v in last_three]
    return _clamp(int(round(sum(scores) / len(scores))))


def compute_targeting_score(
    jds_saved_count: int,
    latest_fit_score: float | None,
    has_target_role: bool,
) -> int:
    """Targeting = jds*15 + (40 if best_fit>=70 else 0) + (30 if role)."""
    raw = jds_saved_count * 15
    if latest_fit_score is not None and latest_fit_score >= 70:
        raw += 40
    if has_target_role:
        raw += 30
    return min(100, max(0, raw))


def compute_overall_readiness(
    skill: int, proof: int, interview: int, targeting: int
) -> int:
    """Weighted overall readiness (skill 40%, proof 25%, interview 20%, targeting 15%)."""
    weighted = (
        skill * 0.40
        + proof * 0.25
        + interview * 0.20
        + targeting * 0.15
    )
    return _clamp(int(round(weighted)))


# ---------------------------------------------------------------------------
# Top-3 action ranker (pure)
# ---------------------------------------------------------------------------


def rank_actions(
    *,
    has_open_weakness: bool,
    mock_weakness_concept: str | None,
    jds_saved_count: int,
    days_since_resume_update: int | None,
    last_fit_score: float | None,
    last_jd_title: str | None,
    days_since_autopsy: int | None,
    latest_verdict_intent: str | None,
    latest_verdict_label: str | None,
    latest_verdict_route: str | None,
    completed_action_kinds: set[str],
) -> list[NextAction]:
    """Apply priority rules in order; skip already-completed kinds; cap at 3.

    Order:
      1. open weakness   → practice_weakness
      2. no JDs saved    → add_jd
      3. resume stale    → refresh_resume (>14d)
      4. fit < 70 + JD   → close_gap_on_jd
      5. no recent autopsy (>30d) → run_autopsy
      6. diagnostic verdict route → diagnostic_verdict
    """
    candidates: list[NextAction] = []

    if has_open_weakness:
        concept = mock_weakness_concept or "your top weakness"
        candidates.append(
            NextAction(
                kind="practice_weakness",
                route="interview",
                label=f"Practice {concept}",
                payload={"concept": mock_weakness_concept},
            )
        )

    if jds_saved_count <= 0:
        candidates.append(
            NextAction(
                kind="add_jd",
                route="jd",
                label="Test yourself against a real JD",
                payload=None,
            )
        )

    if days_since_resume_update is None or days_since_resume_update > 14:
        candidates.append(
            NextAction(
                kind="refresh_resume",
                route="resume",
                label="Refresh your resume",
                payload={"days_since_update": days_since_resume_update},
            )
        )

    if (
        last_fit_score is not None
        and last_fit_score < 70
        and last_jd_title is not None
    ):
        candidates.append(
            NextAction(
                kind="close_gap_on_jd",
                route="jd",
                label=f"Close the gap on {last_jd_title}",
                payload={
                    "fit_score": last_fit_score,
                    "title": last_jd_title,
                },
            )
        )

    if days_since_autopsy is None or days_since_autopsy > 30:
        candidates.append(
            NextAction(
                kind="run_autopsy",
                route="proof",
                label="Run an autopsy on your strongest project",
                payload=None,
            )
        )

    if latest_verdict_route and latest_verdict_label:
        candidates.append(
            NextAction(
                kind="diagnostic_verdict",
                route=latest_verdict_route,
                label=latest_verdict_label,
                payload={"intent": latest_verdict_intent},
            )
        )

    filtered = [a for a in candidates if a.kind not in completed_action_kinds]
    return filtered[:3]


# ---------------------------------------------------------------------------
# Async loader
# ---------------------------------------------------------------------------


@dataclass
class _CountsBundle:
    lessons_completed: int
    lessons_total: int
    capstone_drafts: int
    ai_reviews: int
    autopsies: int


async def _count_lessons(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    completed_q = select(func.count(StudentProgress.id)).where(
        StudentProgress.student_id == user_id,
        StudentProgress.status == "completed",
    )
    total_q = select(func.count(Lesson.id)).where(
        Lesson.is_deleted.is_(False),
        Lesson.is_published.is_(True),
    )
    completed = (await db.execute(completed_q)).scalar_one() or 0
    total = (await db.execute(total_q)).scalar_one() or 0
    return int(completed), int(total)


async def _count_capstone_drafts(db: AsyncSession, user_id: uuid.UUID) -> int:
    q = (
        select(func.count(ExerciseSubmission.id))
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .where(
            ExerciseSubmission.student_id == user_id,
            Exercise.is_capstone.is_(True),
        )
    )
    return int((await db.execute(q)).scalar_one() or 0)


async def _count_ai_reviews(db: AsyncSession, user_id: uuid.UUID) -> int:
    q = select(func.count(AIReview.id)).where(AIReview.user_id == user_id)
    return int((await db.execute(q)).scalar_one() or 0)


async def _count_autopsies(db: AsyncSession, user_id: uuid.UUID) -> int:
    q = select(func.count(PortfolioAutopsyResult.id)).where(
        PortfolioAutopsyResult.user_id == user_id
    )
    return int((await db.execute(q)).scalar_one() or 0)


async def _recent_verdicts(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int = 3
) -> list[str]:
    """Last N mock-session verdict labels (chronological, oldest→newest)."""
    q = (
        select(MockSessionReport.verdict, MockSessionReport.created_at)
        .join(
            InterviewSession,
            InterviewSession.id == MockSessionReport.session_id,
        )
        .where(
            InterviewSession.user_id == user_id,
            MockSessionReport.verdict.is_not(None),
        )
        .order_by(desc(MockSessionReport.created_at))
        .limit(limit)
    )
    rows = (await db.execute(q)).all()
    # Reverse so the most recent is last (matches "take last 3").
    return [str(r[0]) for r in reversed(rows)]


async def _jd_signals(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[int, float | None, str | None]:
    count_q = select(func.count(JdLibrary.id)).where(JdLibrary.user_id == user_id)
    count = int((await db.execute(count_q)).scalar_one() or 0)

    latest_q = (
        select(JdLibrary.last_fit_score, JdLibrary.title)
        .where(
            JdLibrary.user_id == user_id,
            JdLibrary.last_fit_score.is_not(None),
        )
        .order_by(desc(JdLibrary.created_at))
        .limit(1)
    )
    latest_row = (await db.execute(latest_q)).first()
    fit = float(latest_row[0]) if latest_row and latest_row[0] is not None else None
    title = str(latest_row[1]) if latest_row and latest_row[1] is not None else None
    return count, fit, title


async def _open_weakness(
    db: AsyncSession, user_id: uuid.UUID
) -> str | None:
    """Top open weakness concept (severity desc) — None if none open."""
    q = (
        select(MockWeaknessLedger.concept)
        .where(
            MockWeaknessLedger.user_id == user_id,
            MockWeaknessLedger.addressed_at.is_(None),
        )
        .order_by(
            desc(MockWeaknessLedger.severity),
            desc(MockWeaknessLedger.last_seen_at),
        )
        .limit(1)
    )
    row = (await db.execute(q)).first()
    return str(row[0]) if row else None


async def _resume_freshness(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> int | None:
    q = (
        select(Resume.updated_at)
        .where(Resume.user_id == user_id)
        .order_by(desc(Resume.updated_at))
        .limit(1)
    )
    row = (await db.execute(q)).first()
    if row is None or row[0] is None:
        return None
    updated = row[0]
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return max(0, (now - updated).days)


async def _autopsy_freshness(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> int | None:
    q = (
        select(PortfolioAutopsyResult.created_at)
        .where(PortfolioAutopsyResult.user_id == user_id)
        .order_by(desc(PortfolioAutopsyResult.created_at))
        .limit(1)
    )
    row = (await db.execute(q)).first()
    if row is None or row[0] is None:
        return None
    created = row[0]
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max(0, (now - created).days)


async def _latest_verdict(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[
    LatestVerdict | None, str | None, str | None, str | None
]:
    """Latest completed diagnostic session's verdict.

    Returns (LatestVerdict|None, intent, label, route) — the loose
    fields feed the action ranker.
    """
    q = (
        select(ReadinessDiagnosticSession, ReadinessVerdict)
        .join(
            ReadinessVerdict,
            ReadinessVerdict.id == ReadinessDiagnosticSession.verdict_id,
        )
        .where(
            ReadinessDiagnosticSession.user_id == user_id,
            ReadinessDiagnosticSession.verdict_id.is_not(None),
            ReadinessDiagnosticSession.status == DIAGNOSTIC_STATUS_COMPLETED,
        )
        .order_by(desc(ReadinessDiagnosticSession.completed_at))
        .limit(1)
    )
    row = (await db.execute(q)).first()
    if row is None:
        return None, None, None, None
    session, verdict = row
    payload = LatestVerdict(
        session_id=session.id,
        headline=verdict.headline,
        next_action=NextAction(
            kind="diagnostic_verdict",
            route=verdict.next_action_route,
            label=verdict.next_action_label,
            payload={"intent": verdict.next_action_intent},
        ),
        created_at=verdict.created_at,
    )
    return (
        payload,
        verdict.next_action_intent,
        verdict.next_action_label,
        verdict.next_action_route,
    )


async def _trend_8w(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> list[TrendPoint]:
    """Bucket lesson completions into the last 8 ISO weeks.

    Each bucket's "score" is a coarse proxy: clamp(completions * 10).
    The aggregator surfaces this so the Overview spark-line stays honest
    (real weekly activity rather than a fake `44 → 51 → 58 → 62`).
    """
    horizon_start = (now - timedelta(weeks=8)).date()

    q = select(StudentProgress.completed_at).where(
        StudentProgress.student_id == user_id,
        StudentProgress.completed_at.is_not(None),
        StudentProgress.completed_at >= datetime(
            horizon_start.year, horizon_start.month, horizon_start.day, tzinfo=UTC
        ),
    )
    rows = (await db.execute(q)).all()

    buckets: dict[date, int] = {}
    for (completed,) in rows:
        if completed is None:
            continue
        dt = completed
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        # ISO week start (Monday).
        week_start = (dt.date() - timedelta(days=dt.date().weekday()))
        buckets[week_start] = buckets.get(week_start, 0) + 1

    today = now.date()
    this_monday = today - timedelta(days=today.weekday())
    points: list[TrendPoint] = []
    for i in range(7, -1, -1):
        ws = this_monday - timedelta(weeks=i)
        count = buckets.get(ws, 0)
        points.append(TrendPoint(week_start=ws, score=min(100, count * 10)))
    return points


async def _completed_action_kinds(
    db: AsyncSession, user_id: uuid.UUID, *, since: datetime
) -> set[str]:
    """Action kinds the user has cleared recently — drives the dedup."""
    q = select(ReadinessActionCompletion.action_kind).where(
        ReadinessActionCompletion.user_id == user_id,
        ReadinessActionCompletion.completed_at >= since,
    )
    rows = (await db.execute(q)).all()
    return {str(r[0]) for r in rows}


async def _target_role(
    db: AsyncSession, user_id: uuid.UUID
) -> str | None:
    q = (
        select(GoalContract.target_role)
        .where(GoalContract.user_id == user_id)
        .limit(1)
    )
    row = (await db.execute(q)).first()
    return str(row[0]) if row and row[0] else None


async def _north_star_delta(db: AsyncSession) -> NorthStarDelta:
    """Best-effort weekly delta — never raises so it can't sink the page."""
    try:
        from app.services.readiness_north_star import compute_north_star_rate

        current = await compute_north_star_rate(db, window_days=7)
        prior = await compute_north_star_rate(db, window_days=14)
        current_pct = int(round(current.completion_within_24h_rate * 100))
        prior_pct = int(round(prior.completion_within_24h_rate * 100))
        return NorthStarDelta(
            current=current_pct,
            prior=prior_pct,
            delta_week=current_pct - prior_pct,
        )
    except Exception:  # pragma: no cover - defensive
        return NorthStarDelta()


def _first_name(user: User) -> str:
    if not user.full_name:
        return ""
    return user.full_name.strip().split()[0]


async def load_overview(
    db: AsyncSession, *, user: User, now: datetime | None = None
) -> OverviewResponse:
    """Single-fetch payload for the Job Readiness Overview view."""
    current = now or datetime.now(UTC)
    cooldown_start = current - timedelta(days=14)

    (
        lessons,
        capstone_drafts,
        ai_reviews,
        autopsies,
        verdicts,
        jd_bundle,
        weakness_concept,
        resume_days,
        autopsy_days,
        verdict_bundle,
        trend,
        completed_kinds,
        target_role,
        north_star,
    ) = await asyncio.gather(
        _count_lessons(db, user.id),
        _count_capstone_drafts(db, user.id),
        _count_ai_reviews(db, user.id),
        _count_autopsies(db, user.id),
        _recent_verdicts(db, user.id, limit=3),
        _jd_signals(db, user.id),
        _open_weakness(db, user.id),
        _resume_freshness(db, user.id, now=current),
        _autopsy_freshness(db, user.id, now=current),
        _latest_verdict(db, user.id),
        _trend_8w(db, user.id, now=current),
        _completed_action_kinds(db, user.id, since=cooldown_start),
        _target_role(db, user.id),
        _north_star_delta(db),
    )

    lessons_completed, lessons_total = lessons
    jds_count, latest_fit, latest_jd_title = jd_bundle
    latest_verdict_payload, verdict_intent, verdict_label, verdict_route = (
        verdict_bundle
    )

    skill = compute_core_skill_score(lessons_completed, lessons_total)
    proof = compute_proof_score(capstone_drafts, ai_reviews, autopsies)
    interview = compute_interview_score(verdicts)
    targeting = compute_targeting_score(
        jds_count, latest_fit, target_role is not None
    )
    overall = compute_overall_readiness(skill, proof, interview, targeting)

    actions = rank_actions(
        has_open_weakness=weakness_concept is not None,
        mock_weakness_concept=weakness_concept,
        jds_saved_count=jds_count,
        days_since_resume_update=resume_days,
        last_fit_score=latest_fit,
        last_jd_title=latest_jd_title,
        days_since_autopsy=autopsy_days,
        latest_verdict_intent=verdict_intent,
        latest_verdict_label=verdict_label,
        latest_verdict_route=verdict_route,
        completed_action_kinds=completed_kinds,
    )

    return OverviewResponse(
        user_first_name=_first_name(user),
        target_role=target_role,
        overall_readiness=overall,
        sub_scores=SubScores(
            skill=skill, proof=proof, interview=interview, targeting=targeting
        ),
        north_star=north_star,
        top_actions=actions,
        latest_verdict=latest_verdict_payload,
        trend_8w=trend,
    )


__all__ = [
    "compute_core_skill_score",
    "compute_proof_score",
    "compute_interview_score",
    "compute_targeting_score",
    "compute_overall_readiness",
    "rank_actions",
    "load_overview",
]
