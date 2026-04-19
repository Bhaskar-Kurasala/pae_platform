from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.services.retrieval_quiz_service import QuizQuestion

from app.models.student_progress import StudentProgress
from app.models.user import User
from app.repositories.lesson_repository import LessonRepository
from app.repositories.progress_repository import ProgressRepository
from app.schemas.progress import (
    CourseProgress,
    DailyCompletion,
    LessonProgressItem,
    ProgressResponse,
)
from app.services.srs_service import SRSService

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

        # 5. Aggregate cross-cutting KPIs: exercise completion, watch time,
        #    and per-day completion buckets for the activity calendar + weekly
        #    bar chart. All three live on this endpoint so the frontend can
        #    render the full Progress page from a single fetch (DISC-47).
        from app.models.exercise import Exercise
        from app.models.exercise_submission import ExerciseSubmission

        enrolled_course_ids = [course.id for _, course in enrollment_rows]
        total_exercises = 0
        exercises_completed = 0
        if enrolled_course_ids:
            total_ex_res = await self.db.execute(
                select(Exercise)
                .join(Lesson, Exercise.lesson_id == Lesson.id)
                .where(
                    Lesson.course_id.in_(enrolled_course_ids),
                    Exercise.is_deleted.is_(False),
                    Lesson.is_deleted.is_(False),
                )
            )
            total_exercises = len(list(total_ex_res.scalars().all()))

            # A student has "completed" an exercise when ANY of their submissions
            # for it is `graded` with score >= 70 (matches the rubric pass bar).
            sub_res = await self.db.execute(
                select(ExerciseSubmission.exercise_id, ExerciseSubmission.score)
                .where(
                    ExerciseSubmission.student_id == student.id,
                    ExerciseSubmission.status == "graded",
                )
            )
            passed_ids: set[uuid.UUID] = set()
            for ex_id, score in sub_res.all():
                if score is not None and score >= 70:
                    passed_ids.add(ex_id)
            exercises_completed = len(passed_ids)

        ex_rate = (
            round(exercises_completed / total_exercises * 100, 1)
            if total_exercises > 0
            else 0.0
        )

        # Watch time — sum `watch_time_seconds` across every StudentProgress row
        # (captures partial watches too, not just completions).
        watch_total_s = sum(rec.watch_time_seconds for rec in progress_records)
        watch_minutes = watch_total_s // 60

        # Completions by day — bucket `completed_at` timestamps into the last
        # 365 days so the frontend can drive the activity calendar + weekly
        # bar chart without needing a second query.
        day_counts: dict[str, int] = {}
        for rec in progress_records:
            if rec.status != "completed" or rec.completed_at is None:
                continue
            day_counts[rec.completed_at.date().isoformat()] = (
                day_counts.get(rec.completed_at.date().isoformat(), 0) + 1
            )
        completions_by_day = [
            DailyCompletion(date=day, count=count)
            for day, count in sorted(day_counts.items())
        ]

        return ProgressResponse(
            courses=course_progresses,
            overall_progress=overall,
            exercises_completed=exercises_completed,
            total_exercises=total_exercises,
            exercise_completion_rate=ex_rate,
            watch_time_minutes=watch_minutes,
            completions_by_day=completions_by_day,
        )

    async def complete_lesson(self, lesson_id: str | uuid.UUID, student: User) -> StudentProgress:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        await self._auto_enroll_if_free(student.id, lesson_id)
        now = datetime.now(UTC)
        lesson_uuid = (
            lesson_id if isinstance(lesson_id, uuid.UUID) else uuid.UUID(str(lesson_id))
        )
        stmt = (
            pg_insert(StudentProgress)
            .values(
                student_id=student.id,
                lesson_id=lesson_uuid,
                status="completed",
                completed_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_student_progress_student_lesson",
                set_={"status": "completed", "completed_at": now},
            )
        )
        await self.db.execute(stmt)
        await self.db.flush()
        result = await self.db.execute(
            select(StudentProgress).where(
                StudentProgress.student_id == student.id,
                StudentProgress.lesson_id == lesson_uuid,
            )
        )
        progress = result.scalar_one()
        log.info(
            "lesson.completed",
            lesson_id=str(lesson_id),
            student_id=str(student.id),
        )

        # P2-06: every completed lesson seeds a retrieval-practice card so the
        # concept resurfaces on Today. Upsert is idempotent — re-completing a
        # lesson doesn't clobber prior SM-2 state.
        await self._seed_retrieval_card(student.id, lesson_id)
        return progress

    async def uncomplete_lesson(
        self, lesson_id: str | uuid.UUID, student: User
    ) -> None:
        """Delete the student_progress row for (student, lesson). Idempotent.

        DISC-25 — students need a way to recover from mis-clicking "Mark as
        complete". We delete the row outright rather than flipping a status
        field so the aggregation queries (overall %, weekly bars) stay clean
        without additional filters.
        """
        from sqlalchemy import delete

        lesson_uuid = (
            lesson_id if isinstance(lesson_id, uuid.UUID) else uuid.UUID(str(lesson_id))
        )
        await self.db.execute(
            delete(StudentProgress).where(
                StudentProgress.student_id == student.id,
                StudentProgress.lesson_id == lesson_uuid,
            )
        )
        await self.db.flush()
        log.info(
            "lesson.uncompleted",
            lesson_id=str(lesson_id),
            student_id=str(student.id),
        )

    async def _auto_enroll_if_free(
        self, student_id: uuid.UUID, lesson_id: str | uuid.UUID
    ) -> None:
        """Create an active enrollment on first completion of a free-course lesson."""
        from app.repositories.course_repository import CourseRepository
        from app.repositories.enrollment_repository import EnrollmentRepository

        lesson = await self.lesson_repo.get_active(lesson_id)
        if lesson is None:
            return
        course = await CourseRepository(self.db).get_active(lesson.course_id)
        if course is None or course.price_cents > 0:
            return
        enroll_repo = EnrollmentRepository(self.db)
        existing = await enroll_repo.get_by_student_and_course(student_id, course.id)
        if existing is not None:
            return
        await enroll_repo.create(
            {
                "student_id": student_id,
                "course_id": course.id,
                "status": "active",
                "enrolled_at": datetime.now(UTC),
            }
        )
        log.info(
            "enrollment.auto_created",
            student_id=str(student_id),
            course_id=str(course.id),
        )

    async def build_retrieval_quiz(
        self, lesson_id: str | uuid.UUID
    ) -> list[QuizQuestion]:
        """P3 3A-10: returns up to 3 MCQs for the completed lesson.

        Thin pass-through so the route layer can tack a quiz onto the
        completion response without bleeding MCQ imports upward.
        """
        from app.services.retrieval_quiz_service import build_quiz

        lesson_uuid = (
            lesson_id if isinstance(lesson_id, uuid.UUID) else uuid.UUID(str(lesson_id))
        )
        questions = await build_quiz(self.db, lesson_id=lesson_uuid)
        if questions:
            log.info(
                "lesson.retrieval_quiz_shown",
                lesson_id=str(lesson_uuid),
                question_count=len(questions),
            )
        return questions

    async def _seed_retrieval_card(
        self, student_id: uuid.UUID, lesson_id: str | uuid.UUID
    ) -> None:
        lesson = await self.lesson_repo.get_active(lesson_id)
        if lesson is None:
            return
        concept_key = f"lesson:{lesson.slug}"
        prompt = (
            f"Recall — {lesson.title}. In one or two sentences, what is the "
            "core idea and when would you reach for it?"
        )
        try:
            await SRSService(self.db).upsert_card(
                user_id=student_id,
                concept_key=concept_key,
                prompt=prompt,
            )
        except Exception as exc:
            # SRS is a nice-to-have on the completion path — never fail the
            # primary request if the card upsert errors.
            log.warning(
                "retrieval_card.upsert_failed",
                lesson_id=str(lesson_id),
                error=str(exc),
            )
