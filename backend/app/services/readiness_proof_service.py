"""Readiness Proof Portfolio aggregator.

Replaces the Proof Portfolio view's three placeholder cards with a real
artifact list. One async loader queries each evidence source in parallel
and returns the bundle the view needs.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_review import AIReview
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.interview_session import InterviewSession
from app.models.mock_interview import MockSessionReport
from app.models.peer_review import PeerReviewAssignment
from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.models.user import User
from app.schemas.readiness_overview import (
    ProofAIReviewItem,
    ProofAIReviews,
    ProofAutopsy,
    ProofCapstoneArtifact,
    ProofMockReport,
    ProofPeerReviews,
    ProofPrimaryArtifact,
    ProofResponse,
)

log = structlog.get_logger()


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _load_capstones(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> list[ProofCapstoneArtifact]:
    """Per-capstone aggregate: drafts, last score, recency."""
    q = (
        select(
            Exercise.id,
            Exercise.title,
            func.count(ExerciseSubmission.id).label("draft_count"),
            func.max(ExerciseSubmission.updated_at).label("last_edit"),
        )
        .join(
            ExerciseSubmission,
            ExerciseSubmission.exercise_id == Exercise.id,
        )
        .where(
            Exercise.is_capstone.is_(True),
            ExerciseSubmission.student_id == user_id,
        )
        .group_by(Exercise.id, Exercise.title)
        .order_by(desc(func.max(ExerciseSubmission.updated_at)))
    )
    rows = (await db.execute(q)).all()

    artifacts: list[ProofCapstoneArtifact] = []
    for ex_id, title, draft_count, last_edit in rows:
        # Most recent score for this exercise (graded only).
        score_q = (
            select(ExerciseSubmission.score)
            .where(
                ExerciseSubmission.student_id == user_id,
                ExerciseSubmission.exercise_id == ex_id,
                ExerciseSubmission.score.is_not(None),
            )
            .order_by(desc(ExerciseSubmission.created_at))
            .limit(1)
        )
        last_score_row = (await db.execute(score_q)).first()
        last_score = (
            int(last_score_row[0]) if last_score_row and last_score_row[0] is not None else None
        )

        days = None
        aware = _ensure_aware(last_edit)
        if aware is not None:
            days = max(0, (now - aware).days)

        artifacts.append(
            ProofCapstoneArtifact(
                exercise_id=ex_id,
                title=title,
                draft_count=int(draft_count or 0),
                last_score=last_score,
                days_since_last_edit=days,
            )
        )
    return artifacts


async def _load_ai_reviews(
    db: AsyncSession, user_id: uuid.UUID
) -> ProofAIReviews:
    count_q = select(func.count(AIReview.id)).where(AIReview.user_id == user_id)
    count = int((await db.execute(count_q)).scalar_one() or 0)

    last_q = (
        select(AIReview.id, AIReview.problem_id, AIReview.review, AIReview.created_at)
        .where(AIReview.user_id == user_id)
        .order_by(desc(AIReview.created_at))
        .limit(3)
    )
    rows = (await db.execute(last_q)).all()
    items: list[ProofAIReviewItem] = []
    for review_id, problem_id, review_blob, created_at in rows:
        title = None
        if problem_id is not None:
            title_row = (
                await db.execute(
                    select(Exercise.title).where(Exercise.id == problem_id)
                )
            ).first()
            title = str(title_row[0]) if title_row else None

        score: int | None = None
        if isinstance(review_blob, dict):
            raw = review_blob.get("score") or review_blob.get("overall_score")
            if isinstance(raw, (int, float)):
                score = int(raw)

        items.append(
            ProofAIReviewItem(
                id=review_id,
                problem_title=title,
                score=score,
                created_at=created_at,
            )
        )
    return ProofAIReviews(count=count, last_three=items)


async def _load_mock_reports(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ProofMockReport]:
    q = (
        select(
            MockSessionReport.session_id,
            MockSessionReport.headline,
            MockSessionReport.verdict,
            MockSessionReport.created_at,
            InterviewSession.target_role,
        )
        .join(
            InterviewSession,
            InterviewSession.id == MockSessionReport.session_id,
        )
        .where(InterviewSession.user_id == user_id)
        .order_by(desc(MockSessionReport.created_at))
        .limit(3)
    )
    rows = (await db.execute(q)).all()
    return [
        ProofMockReport(
            session_id=session_id,
            headline=headline,
            verdict=verdict,
            created_at=created_at,
            target_role=target_role,
        )
        for session_id, headline, verdict, created_at, target_role in rows
    ]


async def _load_autopsies(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ProofAutopsy]:
    q = (
        select(PortfolioAutopsyResult)
        .where(PortfolioAutopsyResult.user_id == user_id)
        .order_by(desc(PortfolioAutopsyResult.created_at))
        .limit(5)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        ProofAutopsy(
            id=row.id,
            project_title=row.project_title,
            headline=row.headline,
            overall_score=int(row.overall_score),
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _load_peer_reviews(
    db: AsyncSession, user_id: uuid.UUID
) -> ProofPeerReviews:
    """Reviews received = on submissions student authored.
    Reviews given = where reviewer_id == user_id.
    Both counts only include completed (rating present) rows.
    """
    received_q = (
        select(func.count(PeerReviewAssignment.id))
        .join(
            ExerciseSubmission,
            ExerciseSubmission.id == PeerReviewAssignment.submission_id,
        )
        .where(
            ExerciseSubmission.student_id == user_id,
            PeerReviewAssignment.completed_at.is_not(None),
        )
    )
    given_q = select(func.count(PeerReviewAssignment.id)).where(
        PeerReviewAssignment.reviewer_id == user_id,
        PeerReviewAssignment.completed_at.is_not(None),
    )
    received = int((await db.execute(received_q)).scalar_one() or 0)
    given = int((await db.execute(given_q)).scalar_one() or 0)
    return ProofPeerReviews(count_received=received, count_given=given)


async def _last_capstone_summary(
    db: AsyncSession, user_id: uuid.UUID
) -> ProofPrimaryArtifact | None:
    """Headline card on Proof: latest capstone draft, with a code snippet."""
    q = (
        select(Exercise.title, ExerciseSubmission.code)
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .where(
            ExerciseSubmission.student_id == user_id,
            Exercise.is_capstone.is_(True),
        )
        .order_by(desc(ExerciseSubmission.created_at))
        .limit(1)
    )
    row = (await db.execute(q)).first()
    if row is None:
        return None
    title, code = row
    snippet = None
    if isinstance(code, str) and code.strip():
        snippet = code.strip().splitlines()[0][:200]
    return ProofPrimaryArtifact(title=title, snippet=snippet)


async def load_proof(
    db: AsyncSession, *, user: User, now: datetime | None = None
) -> ProofResponse:
    current = now or datetime.now(UTC)

    (
        capstones,
        ai_reviews,
        mock_reports,
        autopsies,
        peer_reviews,
        primary,
    ) = await asyncio.gather(
        _load_capstones(db, user.id, now=current),
        _load_ai_reviews(db, user.id),
        _load_mock_reports(db, user.id),
        _load_autopsies(db, user.id),
        _load_peer_reviews(db, user.id),
        _last_capstone_summary(db, user.id),
    )

    return ProofResponse(
        capstone_artifacts=capstones,
        ai_reviews=ai_reviews,
        mock_reports=mock_reports,
        autopsies=autopsies,
        peer_reviews=peer_reviews,
        last_capstone_summary=primary,
    )


__all__ = ["load_proof"]
