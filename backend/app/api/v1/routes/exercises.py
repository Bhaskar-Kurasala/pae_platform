import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.user import User
from app.schemas.exercise import ExerciseResponse
from app.schemas.submission import SubmissionCreate, SubmissionResponse
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
    return await service.submit(exercise_id, payload, current_user)
