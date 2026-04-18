import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.user import User
from app.schemas.exercise import ExerciseResponse
from app.schemas.submission import (
    PeerSubmissionItem,
    ShareUpdate,
    SubmissionCreate,
    SubmissionResponse,
)
from app.services.exercise_service import ExerciseService

router = APIRouter(prefix="/exercises", tags=["exercises"])


def get_service(db: AsyncSession = Depends(get_db)) -> ExerciseService:
    return ExerciseService(db)


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


@router.patch(
    "/submissions/{submission_id}/share",
    response_model=SubmissionResponse,
)
async def update_share_settings(
    submission_id: uuid.UUID,
    payload: ShareUpdate,
    service: ExerciseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ExerciseSubmission:
    """Toggle `shared_with_peers` / `share_note` on your own submission."""
    return await service.update_share(
        submission_id,
        student_id=current_user.id,
        shared_with_peers=payload.shared_with_peers,
        share_note=payload.share_note,
    )
