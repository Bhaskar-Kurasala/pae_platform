import uuid
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import Enrollment
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository

log = structlog.get_logger()


class EnrollmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.enrollment_repo = EnrollmentRepository(db)
        self.course_repo = CourseRepository(db)

    async def enroll_student(self, course_id: uuid.UUID, current_user: User) -> Enrollment:
        course = await self.course_repo.get_active(course_id)
        if not course:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

        if not course.is_published:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

        existing = await self.enrollment_repo.get_by_student_and_course(
            current_user.id, course_id
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Already enrolled in this course",
            )

        enrollment = await self.enrollment_repo.create(
            {
                "student_id": current_user.id,
                "course_id": course_id,
                "status": "active",
                "enrolled_at": datetime.now(UTC),
                "progress_pct": 0.0,
            }
        )
        log.info(
            "enrollment.created",
            student_id=str(current_user.id),
            course_id=str(course_id),
            enrollment_id=str(enrollment.id),
        )
        return enrollment
