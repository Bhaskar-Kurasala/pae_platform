import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.models.user import User
from app.repositories.lesson_repository import LessonRepository
from app.schemas.lesson import LessonCreate, LessonUpdate

log = structlog.get_logger()


class LessonService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = LessonRepository(db)

    def _require_admin(self, user: User) -> None:
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    async def get_lessons_for_course(self, course_id: str | uuid.UUID) -> list[Lesson]:
        return await self.repo.get_by_course(course_id)

    async def get_lesson(self, lesson_id: str | uuid.UUID) -> Lesson:
        lesson = await self.repo.get_active(lesson_id)
        if not lesson:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
        return lesson

    async def create_lesson(self, payload: LessonCreate, user: User) -> Lesson:
        self._require_admin(user)
        lesson = await self.repo.create(payload.model_dump())
        log.info("lesson.created", lesson_id=str(lesson.id))
        return lesson

    async def update_lesson(
        self, lesson_id: str | uuid.UUID, payload: LessonUpdate, user: User
    ) -> Lesson:
        self._require_admin(user)
        lesson = await self.get_lesson(lesson_id)
        return await self.repo.update(lesson, payload.model_dump(exclude_none=True))
