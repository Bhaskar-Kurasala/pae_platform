import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import Enrollment
from app.repositories.base import BaseRepository


class EnrollmentRepository(BaseRepository[Enrollment]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Enrollment, db)

    async def get_by_student_and_course(
        self, student_id: uuid.UUID, course_id: uuid.UUID
    ) -> Enrollment | None:
        result = await self.db.execute(
            select(Enrollment).where(
                Enrollment.student_id == student_id,
                Enrollment.course_id == course_id,
            )
        )
        return result.scalar_one_or_none()
