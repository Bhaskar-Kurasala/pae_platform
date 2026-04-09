import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.schemas.progress import LessonProgressRecord, ProgressResponse
from app.services.progress_service import ProgressService

router = APIRouter(prefix="/students", tags=["students"])


def get_service(db: AsyncSession = Depends(get_db)) -> ProgressService:
    return ProgressService(db)


@router.get("/me/progress", response_model=ProgressResponse)
async def get_my_progress(
    service: ProgressService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ProgressResponse:
    return await service.get_student_progress(current_user)


@router.post("/me/lessons/{lesson_id}/complete", response_model=LessonProgressRecord)
async def complete_lesson(
    lesson_id: uuid.UUID,
    service: ProgressService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> StudentProgress:
    return await service.complete_lesson(lesson_id, current_user)
