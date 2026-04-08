import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_progress import StudentProgress
from app.models.user import User
from app.repositories.progress_repository import ProgressRepository

log = structlog.get_logger()


class ProgressService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = ProgressRepository(db)

    async def get_student_progress(self, student: User) -> list[StudentProgress]:
        return await self.repo.get_by_student(student.id)

    async def complete_lesson(self, lesson_id: str | uuid.UUID, student: User) -> StudentProgress:
        existing = await self.repo.get_for_lesson(student.id, lesson_id)
        now = datetime.now(UTC)
        if existing:
            return await self.repo.update(
                existing,
                {"status": "completed", "completed_at": now},
            )
        progress = await self.repo.create(
            {
                "student_id": student.id,
                "lesson_id": lesson_id,
                "status": "completed",
                "completed_at": now,
            }
        )
        log.info(
            "lesson.completed",
            lesson_id=str(lesson_id),
            student_id=str(student.id),
        )
        return progress
