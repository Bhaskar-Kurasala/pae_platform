import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.user import User
from app.schemas.exercise import ExerciseResponse
from app.schemas.difficulty import DifficultyRecommendationResponse
from app.schemas.fading_scaffolds import FadedScaffoldResponse
from app.schemas.interleaving import InterleavingSuggestionResponse
from app.schemas.peer_review import (
    PeerReviewAssignmentItem,
    PeerReviewSubmit,
    PendingReviewsResponse,
    SubmissionPeerReviewsResponse,
)
from app.schemas.submission import (
    PeerSubmissionItem,
    ShareUpdate,
    SubmissionCreate,
    SubmissionResponse,
)
from app.schemas.worked_example import WorkedExampleResponse
from app.services.difficulty_service import compute_recommendation
from app.services.exercise_service import ExerciseService
from app.services.fading_scaffolds_service import fade_scaffolds
from app.services.interleaving_service import compute_suggestion
from app.services.peer_review_service import (
    assign_reviewers,
    list_pending_for_reviewer,
    list_reviews_for_submission,
    submit_review,
)
from app.services.worked_example_service import fetch_worked_example

log = structlog.get_logger()

router = APIRouter(prefix="/exercises", tags=["exercises"])


def get_service(db: AsyncSession = Depends(get_db)) -> ExerciseService:
    return ExerciseService(db)


@router.get("", response_model=list[ExerciseResponse])
async def list_exercises(
    limit: int = Query(default=50, ge=1, le=100),
    service: ExerciseService = Depends(get_service),
) -> list[Exercise]:
    return await service.exercise_repo.list_active(limit=limit)


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: uuid.UUID,
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ExerciseSubmission:
    submission = await service.submission_repo.get_by_id(submission_id)
    from fastapi import HTTPException
    if submission is None or submission.student_id != current_user.id:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission


@router.get("/{exercise_id}/submissions/mine", response_model=list[SubmissionResponse])
async def list_my_submissions(
    exercise_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=50),
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> list[ExerciseSubmission]:
    return await service.submission_repo.list_mine_for_exercise(
        current_user.id, exercise_id, limit=limit
    )


@router.get("/{exercise_id}", response_model=ExerciseResponse)
async def get_exercise(
    exercise_id: uuid.UUID,
    service: ExerciseService = Depends(get_service),
) -> Exercise:
    return await service.get_exercise(exercise_id)


@router.post("/{exercise_id}/submit", response_model=SubmissionResponse, status_code=201)
async def submit_exercise(
    exercise_id: uuid.UUID,
    payload: SubmissionCreate,
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ExerciseSubmission:
    payload.exercise_id = exercise_id
    return await service.submit(exercise_id, payload, current_user)


@router.get(
    "/{exercise_id}/peer-gallery",
    response_model=list[PeerSubmissionItem],
)
async def get_peer_gallery(
    exercise_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=50),
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> list[PeerSubmissionItem]:
    """P2-07: anonymous peer-solutions gallery for a completed exercise."""
    items = await service.list_peer_gallery(
        exercise_id, viewer_id=current_user.id, limit=limit
    )
    return [PeerSubmissionItem.model_validate(i) for i in items]


@router.get(
    "/{exercise_id}/scaffold-envelope",
    response_model=FadedScaffoldResponse,
)
async def get_scaffold_envelope(
    exercise_id: uuid.UUID,
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> FadedScaffoldResponse:
    """How many hint levels are still available on this exercise (P3 3B #92)."""
    exercise = await service.get_exercise(exercise_id)
    attempts = await service.submission_repo.count_attempts(
        current_user.id, exercise.id
    )
    envelope = fade_scaffolds(attempts + 1)
    log.info(
        "lesson.scaffolds_faded",
        user_id=str(current_user.id),
        exercise_id=str(exercise_id),
        attempt=envelope.attempt_number,
        allowed=len(envelope.allowed_levels),
    )
    return FadedScaffoldResponse(
        attempt_number=envelope.attempt_number,
        allowed_levels=list(envelope.allowed_levels),
        faded=envelope.faded,
        reason=envelope.reason,
    )


@router.get(
    "/{exercise_id}/worked-example",
    response_model=WorkedExampleResponse,
)
async def get_worked_example(
    exercise_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> WorkedExampleResponse:
    """Show a worked example of a similar problem (P3 3B #91)."""
    exercise = await service.get_exercise(exercise_id)
    example = await fetch_worked_example(
        db, user_id=current_user.id, exercise=exercise
    )
    if example is None:
        return WorkedExampleResponse(available=False)
    log.info(
        "lesson.worked_example_shown",
        user_id=str(current_user.id),
        exercise_id=str(exercise_id),
        source=example.source,
    )
    return WorkedExampleResponse(
        available=True,
        exercise_title=example.exercise_title,
        code_snippet=example.code_snippet,
        note=example.note,
        source=example.source,
    )


@router.get(
    "/{exercise_id}/difficulty-recommendation",
    response_model=DifficultyRecommendationResponse,
)
async def get_difficulty_recommendation(
    exercise_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> DifficultyRecommendationResponse:
    """Desirable-difficulty recommendation based on last-5 outcomes (P3 3B #90)."""
    exercise = await service.get_exercise(exercise_id)
    rec = await compute_recommendation(
        db, user_id=current_user.id, exercise=exercise
    )
    if rec.current != rec.recommended:
        log.info(
            "lesson.difficulty_adjusted",
            user_id=str(current_user.id),
            exercise_id=str(exercise_id),
            from_level=rec.current,
            to_level=rec.recommended,
        )
    return DifficultyRecommendationResponse(
        current=rec.current, recommended=rec.recommended, reason=rec.reason
    )


@router.get(
    "/interleaving/suggestion",
    response_model=InterleavingSuggestionResponse,
)
async def get_interleaving_suggestion(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterleavingSuggestionResponse:
    """Suggest moving to an adjacent skill after 3-in-a-row (P3 3B #85)."""
    suggestion = await compute_suggestion(db, user_id=current_user.id)
    if suggestion.suggest:
        log.info(
            "lesson.interleaving_suggested",
            user_id=str(current_user.id),
            current_skill=str(suggestion.current_skill_id),
            next_skill=str(suggestion.next_skill_id),
        )
    return InterleavingSuggestionResponse(
        suggest=suggestion.suggest,
        current_skill_id=suggestion.current_skill_id,
        next_skill_id=suggestion.next_skill_id,
        reason=suggestion.reason,
    )


@router.patch(
    "/submissions/{submission_id}/share",
    response_model=SubmissionResponse,
)
async def update_share_settings(
    submission_id: uuid.UUID,
    payload: ShareUpdate,
    db: AsyncSession = Depends(get_db),
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ExerciseSubmission:
    """Toggle `shared_with_peers` / `share_note` on your own submission."""
    submission = await service.update_share(
        submission_id,
        student_id=current_user.id,
        shared_with_peers=payload.shared_with_peers,
        share_note=payload.share_note,
    )
    if payload.shared_with_peers:
        created = await assign_reviewers(db, submission=submission)
        if created:
            log.info(
                "community.peer_reviews_assigned",
                submission_id=str(submission.id),
                reviewer_count=len(created),
            )
    return submission


@router.get(
    "/peer-reviews/pending",
    response_model=PendingReviewsResponse,
)
async def get_pending_peer_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PendingReviewsResponse:
    """Submissions assigned to me for peer review (P3 3B #101)."""
    rows = await list_pending_for_reviewer(db, reviewer_id=current_user.id)
    return PendingReviewsResponse(
        assignments=[PeerReviewAssignmentItem.model_validate(r) for r in rows]
    )


@router.post(
    "/peer-reviews/{assignment_id}",
    response_model=PeerReviewAssignmentItem,
)
async def submit_peer_review(
    assignment_id: uuid.UUID,
    payload: PeerReviewSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PeerReviewAssignmentItem:
    """Fill in the rating+comment for an assigned peer review."""
    row = await submit_review(
        db,
        assignment_id=assignment_id,
        reviewer_id=current_user.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    log.info(
        "community.peer_review_submitted",
        assignment_id=str(assignment_id),
        reviewer_id=str(current_user.id),
        rating=row.rating,
    )
    return PeerReviewAssignmentItem.model_validate(row)


@router.get(
    "/submissions/{submission_id}/peer-reviews",
    response_model=SubmissionPeerReviewsResponse,
)
async def get_submission_peer_reviews(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubmissionPeerReviewsResponse:
    """Completed peer reviews on a submission (author-visible)."""
    rows = await list_reviews_for_submission(db, submission_id=submission_id)
    return SubmissionPeerReviewsResponse(
        reviews=[PeerReviewAssignmentItem.model_validate(r) for r in rows]
    )
