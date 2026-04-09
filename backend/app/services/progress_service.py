import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_progress import StudentProgress
from app.models.user import User
from app.repositories.lesson_repository import LessonRepository
from app.repositories.progress_repository import ProgressRepository
from app.schemas.progress import (
    CourseProgress,
    LessonProgressItem,
    ProgressResponse,
)

log = structlog.get_logger()


class ProgressService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProgressRepository(db)
        self.lesson_repo = LessonRepository(db)

    async def get_student_progress(self, student: User) -> ProgressResponse:
        from sqlalchemy import select

        from app.models.course import Course
        from app.models.enrollment import Enrollment
        from app.models.lesson import Lesson

        # 1. Fetch all active enrollments with the course
        enrollment_result = await self.db.execute(
            select(Enrollment, Course)
            .join(Course, Enrollment.course_id == Course.id)
            .where(
                Enrollment.student_id == student.id,
                Enrollment.status == "active",
            )
        )
        enrollment_rows = enrollment_result.all()

        if not enrollment_rows:
            return ProgressResponse(courses=[], overall_progress=0.0)

        # 2. Build lesson_id → status map from student_progress
        progress_records = await self.repo.get_by_student(student.id)
        lesson_status: dict[uuid.UUID, str] = {
            rec.lesson_id: rec.status for rec in progress_records
        }

        # 3. Build CourseProgress for each enrolled course
        course_progresses: list[CourseProgress] = []

        for _enrollment, course in enrollment_rows:
            lessons_result = await self.db.execute(
                select(Lesson)
                .where(Lesson.course_id == course.id, Lesson.is_deleted.is_(False))
                .order_by(Lesson.order)
            )
            lessons = list(lessons_result.scalars().all())

            total = len(lessons)
            completed = 0
            next_lesson_id: uuid.UUID | None = None
            next_lesson_title: str | None = None
            lesson_items: list[LessonProgressItem] = []

            for lesson in lessons:
                status = lesson_status.get(lesson.id, "not_started")
                if status == "completed":
                    completed += 1
                elif next_lesson_id is None:
                    # First non-completed lesson is the "next" one
                    next_lesson_id = lesson.id
                    next_lesson_title = lesson.title

                lesson_items.append(
                    LessonProgressItem(
                        id=lesson.id,
                        title=lesson.title,
                        order=lesson.order,
                        status=status,
                    )
                )

            pct = round(completed / total * 100, 1) if total > 0 else 0.0

            course_progresses.append(
                CourseProgress(
                    course_id=course.id,
                    course_title=course.title,
                    total_lessons=total,
                    completed_lessons=completed,
                    progress_percentage=pct,
                    next_lesson_id=next_lesson_id,
                    next_lesson_title=next_lesson_title,
                    lessons=lesson_items,
                )
            )

        # 4. Overall progress = average of per-course percentages
        overall = (
            round(sum(c.progress_percentage for c in course_progresses) / len(course_progresses), 1)
            if course_progresses
            else 0.0
        )

        return ProgressResponse(courses=course_progresses, overall_progress=overall)

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
