import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.repositories.base import BaseRepository


class ExerciseRepository(BaseRepository[Exercise]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Exercise, db)

    async def get_by_lesson(self, lesson_id: str | uuid.UUID) -> list[Exercise]:
        result = await self.db.execute(
            select(Exercise)
            .where(Exercise.lesson_id == lesson_id, Exercise.is_deleted.is_(False))
            .order_by(Exercise.order)
        )
        return list(result.scalars().all())

    async def get_active(self, id: str | uuid.UUID) -> Exercise | None:
        result = await self.db.execute(
            select(Exercise).where(Exercise.id == id, Exercise.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()


class SubmissionRepository(BaseRepository[ExerciseSubmission]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(ExerciseSubmission, db)

    async def get_by_student_exercise(
        self, student_id: str | uuid.UUID, exercise_id: str | uuid.UUID
    ) -> list[ExerciseSubmission]:
        result = await self.db.execute(
            select(ExerciseSubmission).where(
                ExerciseSubmission.student_id == student_id,
                ExerciseSubmission.exercise_id == exercise_id,
            )
        )
        return list(result.scalars().all())

    async def count_attempts(
        self, student_id: str | uuid.UUID, exercise_id: str | uuid.UUID
    ) -> int:
        rows = await self.get_by_student_exercise(student_id, exercise_id)
        return len(rows)
