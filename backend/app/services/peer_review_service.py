"""Peer review exchange (P3 3B #101).

Thin service on top of `peer_review_assignments`. Pure helpers pick
reviewers and validate rating payloads; async loaders + mutators
persist to the DB.

Reviewer selection: eligible pool = other students who've also
submitted to the same exercise (shared or not) — keeps reviewers in
the relevant context. Capped at `_MAX_REVIEWERS_PER_SUBMISSION`.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise_submission import ExerciseSubmission
from app.models.peer_review import PeerReviewAssignment

_MAX_REVIEWERS_PER_SUBMISSION = 2
_MIN_RATING = 1
_MAX_RATING = 5
_MAX_COMMENT_LEN = 2000


def pick_reviewers(
    candidate_ids: Sequence[UUID],
    *,
    author_id: UUID,
    existing_reviewers: Sequence[UUID] = (),
    max_reviewers: int = _MAX_REVIEWERS_PER_SUBMISSION,
    rng: random.Random | None = None,
) -> list[UUID]:
    """Choose up to N reviewers, excluding the author and existing picks."""
    exclude = {author_id, *existing_reviewers}
    pool = [c for c in candidate_ids if c not in exclude]
    needed = max(max_reviewers - len(existing_reviewers), 0)
    if needed <= 0 or not pool:
        return []
    sampler = rng or random.Random()
    sampler.shuffle(pool)
    return pool[:needed]


def validate_review(rating: int, comment: str | None) -> tuple[int, str | None]:
    """Validate a review payload; returns normalized `(rating, comment)`."""
    if rating < _MIN_RATING or rating > _MAX_RATING:
        raise ValueError(
            f"rating must be {_MIN_RATING}..{_MAX_RATING}, got {rating}"
        )
    if comment is not None:
        cleaned = comment.strip()
        if not cleaned:
            return rating, None
        return rating, cleaned[:_MAX_COMMENT_LEN]
    return rating, None


async def _eligible_reviewer_ids(
    db: AsyncSession, *, exercise_id: UUID, exclude: UUID
) -> list[UUID]:
    result = await db.execute(
        select(ExerciseSubmission.student_id)
        .where(
            ExerciseSubmission.exercise_id == exercise_id,
            ExerciseSubmission.student_id != exclude,
        )
        .distinct()
    )
    return [row[0] for row in result.all()]


async def assign_reviewers(
    db: AsyncSession,
    *,
    submission: ExerciseSubmission,
    max_reviewers: int = _MAX_REVIEWERS_PER_SUBMISSION,
) -> list[PeerReviewAssignment]:
    """Assign fresh reviewers to a shared submission (idempotent top-up)."""
    existing = await db.execute(
        select(PeerReviewAssignment.reviewer_id).where(
            PeerReviewAssignment.submission_id == submission.id
        )
    )
    existing_ids = [row[0] for row in existing.all()]

    candidates = await _eligible_reviewer_ids(
        db, exercise_id=submission.exercise_id, exclude=submission.student_id
    )
    chosen = pick_reviewers(
        candidates,
        author_id=submission.student_id,
        existing_reviewers=existing_ids,
        max_reviewers=max_reviewers,
    )

    created: list[PeerReviewAssignment] = []
    for reviewer_id in chosen:
        row = PeerReviewAssignment(
            submission_id=submission.id, reviewer_id=reviewer_id
        )
        db.add(row)
        created.append(row)
    if created:
        await db.flush()
        for r in created:
            await db.refresh(r)
    return created


async def list_pending_for_reviewer(
    db: AsyncSession, *, reviewer_id: UUID, limit: int = 20
) -> list[PeerReviewAssignment]:
    result = await db.execute(
        select(PeerReviewAssignment)
        .where(
            PeerReviewAssignment.reviewer_id == reviewer_id,
            PeerReviewAssignment.completed_at.is_(None),
        )
        .order_by(PeerReviewAssignment.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_reviews_for_submission(
    db: AsyncSession, *, submission_id: UUID
) -> list[PeerReviewAssignment]:
    result = await db.execute(
        select(PeerReviewAssignment)
        .where(
            PeerReviewAssignment.submission_id == submission_id,
            PeerReviewAssignment.completed_at.is_not(None),
        )
        .order_by(PeerReviewAssignment.completed_at.asc())
    )
    return list(result.scalars().all())


async def submit_review(
    db: AsyncSession,
    *,
    assignment_id: UUID,
    reviewer_id: UUID,
    rating: int,
    comment: str | None,
) -> PeerReviewAssignment:
    """Reviewer fills in rating+comment on an assigned submission."""
    row = await db.get(PeerReviewAssignment, assignment_id)
    if row is None or row.reviewer_id != reviewer_id:
        raise HTTPException(status_code=404, detail="assignment not found")
    if row.completed_at is not None:
        raise HTTPException(status_code=409, detail="review already submitted")

    normalized_rating, normalized_comment = validate_review(rating, comment)
    row.rating = normalized_rating
    row.comment = normalized_comment
    row.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(row)
    return row


__all__ = [
    "assign_reviewers",
    "list_pending_for_reviewer",
    "list_reviews_for_submission",
    "pick_reviewers",
    "submit_review",
    "validate_review",
]
