import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.repositories.base import BaseRepository


class LessonRepository(BaseRepository[Lesson]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Lesson, db)

    async def get_by_course(self, course_id: str | uuid.UUID) -> list[Lesson]:
        result = await self.db.execute(
            select(Lesson)
            .where(Lesson.course_id == course_id, Lesson.is_deleted.is_(False))
            .order_by(Lesson.order)
        )
        return list(result.scalars().all())

    async def get_active(self, id: str | uuid.UUID) -> Lesson | None:
        result = await self.db.execute(
            select(Lesson).where(Lesson.id == id, Lesson.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()
