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

    async def list_active(self, limit: int = 50) -> list[Exercise]:
        result = await self.db.execute(
            select(Exercise)
            .where(Exercise.is_deleted.is_(False))
            .order_by(Exercise.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


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

    async def list_shared_for_exercise(
        self,
        exercise_id: str | uuid.UUID,
        *,
        exclude_student_id: str | uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[ExerciseSubmission]:
        """Shared submissions for an exercise, newest first.

        Only returns submissions that opted in (`shared_with_peers=True`). The
        caller typically excludes their own submissions via `exclude_student_id`.
        """
        stmt = (
            select(ExerciseSubmission)
            .where(
                ExerciseSubmission.exercise_id == exercise_id,
                ExerciseSubmission.shared_with_peers.is_(True),
            )
            .order_by(ExerciseSubmission.created_at.desc())
            .limit(limit)
        )
        if exclude_student_id is not None:
            stmt = stmt.where(ExerciseSubmission.student_id != exclude_student_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, submission_id: str | uuid.UUID) -> ExerciseSubmission | None:
        result = await self.db.execute(
            select(ExerciseSubmission).where(ExerciseSubmission.id == submission_id)
        )
        return result.scalar_one_or_none()

    async def list_mine_for_exercise(
        self,
        student_id: str | uuid.UUID,
        exercise_id: str | uuid.UUID,
        limit: int = 20,
    ) -> list[ExerciseSubmission]:
        result = await self.db.execute(
            select(ExerciseSubmission)
            .where(
                ExerciseSubmission.student_id == student_id,
                ExerciseSubmission.exercise_id == exercise_id,
            )
            .order_by(ExerciseSubmission.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
