import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.user import User
from app.repositories.exercise_repository import ExerciseRepository, SubmissionRepository
from app.schemas.submission import SubmissionCreate

log = structlog.get_logger()


class ExerciseService:
    def __init__(self, db: AsyncSession) -> None:
        self.exercise_repo = ExerciseRepository(db)
        self.submission_repo = SubmissionRepository(db)

    async def get_exercise(self, exercise_id: str | uuid.UUID) -> Exercise:
        exercise = await self.exercise_repo.get_active(exercise_id)
        if not exercise:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")
        return exercise

    async def get_exercises_for_lesson(self, lesson_id: str | uuid.UUID) -> list[Exercise]:
        return await self.exercise_repo.get_by_lesson(lesson_id)

    async def submit(
        self, exercise_id: str | uuid.UUID, payload: SubmissionCreate, student: User
    ) -> ExerciseSubmission:
        exercise = await self.get_exercise(exercise_id)
        attempt = await self.submission_repo.count_attempts(student.id, exercise.id) + 1
        submission = await self.submission_repo.create(
            {
                "student_id": student.id,
                "exercise_id": exercise.id,
                "code": payload.code,
                "github_pr_url": payload.github_pr_url,
                "status": "pending",
                "attempt_number": attempt,
            }
        )
        log.info(
            "exercise.submitted",
            submission_id=str(submission.id),
            student_id=str(student.id),
            attempt=attempt,
        )
        return submission
