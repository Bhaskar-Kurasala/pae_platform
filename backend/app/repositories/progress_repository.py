import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_progress import StudentProgress
from app.repositories.base import BaseRepository


class ProgressRepository(BaseRepository[StudentProgress]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(StudentProgress, db)

    async def get_by_student(self, student_id: str | uuid.UUID) -> list[StudentProgress]:
        result = await self.db.execute(
            select(StudentProgress).where(StudentProgress.student_id == student_id)
        )
        return list(result.scalars().all())

    async def get_for_lesson(
        self, student_id: str | uuid.UUID, lesson_id: str | uuid.UUID
    ) -> StudentProgress | None:
        result = await self.db.execute(
            select(StudentProgress).where(
                StudentProgress.student_id == student_id,
                StudentProgress.lesson_id == lesson_id,
            )
        )
        return result.scalar_one_or_none()
