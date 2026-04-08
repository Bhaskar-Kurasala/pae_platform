import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.lesson import LessonCreate, LessonResponse, LessonUpdate
from app.services.lesson_service import LessonService

router = APIRouter(tags=["lessons"])


def get_service(db: AsyncSession = Depends(get_db)) -> LessonService:
    return LessonService(db)


@router.get("/courses/{course_id}/lessons", response_model=list[LessonResponse])
async def list_lessons(
    course_id: uuid.UUID,
    service: LessonService = Depends(get_service),
) -> list[Lesson]:
    return await service.get_lessons_for_course(course_id)


@router.get("/lessons/{lesson_id}", response_model=LessonResponse)
async def get_lesson(
    lesson_id: uuid.UUID,
    service: LessonService = Depends(get_service),
) -> Lesson:
    return await service.get_lesson(lesson_id)


@router.post("/lessons", response_model=LessonResponse, status_code=201)
async def create_lesson(
    payload: LessonCreate,
    service: LessonService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> Lesson:
    return await service.create_lesson(payload, current_user)


@router.put("/lessons/{lesson_id}", response_model=LessonResponse)
async def update_lesson(
    lesson_id: uuid.UUID,
    payload: LessonUpdate,
    service: LessonService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> Lesson:
    return await service.update_lesson(lesson_id, payload, current_user)
