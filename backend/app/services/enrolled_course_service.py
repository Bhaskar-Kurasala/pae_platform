"""EnrolledCourseService — derives "courses the student has actually started".

A student is *enrolled* in a course (for Path-screen purposes) iff they have
at least one ``student_asset_progress`` row tied to that course. Free
catalog browse access alone does not count — we want the Path screen to
surface "courses you're working through," not "courses you can theoretically
open."

This is a deliberate definition choice over adding a new `enrollments`
column: the existing `student_asset_progress.updated_at` already encodes
both "have they started?" and "how recently?" in one signal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_asset import LessonAsset
from app.models.student_asset_progress import StudentAssetProgress
from app.models.student_progress import StudentProgress


@dataclass(frozen=True)
class EnrolledCourse:
    course_id: uuid.UUID
    course_slug: str
    course_title: str
    progress_pct: float
    total_lessons: int
    completed_lessons: int
    last_touched_at: datetime | None


async def list_enrolled_courses(
    db: AsyncSession, *, student_id: uuid.UUID
) -> list[EnrolledCourse]:
    """All courses where the student has any asset-progress row.

    One round-trip per data slice (touched courses, lesson counts,
    completion counts), composed in Python. Cheaper than a single
    monster CTE and easier to reason about.
    """
    # 1. Courses the student has touched + the most recent touch per course.
    touched_stmt = (
        select(
            Lesson.course_id.label("course_id"),
            func.max(StudentAssetProgress.updated_at).label("last_touched_at"),
        )
        .join(LessonAsset, LessonAsset.id == StudentAssetProgress.asset_id)
        .join(Lesson, Lesson.id == LessonAsset.lesson_id)
        .where(StudentAssetProgress.student_id == student_id)
        .group_by(Lesson.course_id)
    )
    touched_rows = (await db.execute(touched_stmt)).all()
    if not touched_rows:
        return []
    course_ids = [row.course_id for row in touched_rows]
    last_touched_by_course: dict[uuid.UUID, datetime] = {
        row.course_id: row.last_touched_at for row in touched_rows
    }

    # 2. Course metadata.
    course_stmt = select(Course).where(
        Course.id.in_(course_ids), Course.is_published.is_(True)
    )
    courses = {c.id: c for c in (await db.execute(course_stmt)).scalars().all()}

    # 3. Lesson counts per course (published only).
    total_stmt = (
        select(Lesson.course_id, func.count(Lesson.id))
        .where(
            Lesson.course_id.in_(course_ids), Lesson.is_published.is_(True)
        )
        .group_by(Lesson.course_id)
    )
    totals = {row[0]: row[1] for row in (await db.execute(total_stmt)).all()}

    # 4. Completed-lesson counts per course.
    completed_stmt = (
        select(
            Lesson.course_id,
            func.sum(
                case((StudentProgress.completed_at.isnot(None), 1), else_=0)
            ),
        )
        .join(StudentProgress, StudentProgress.lesson_id == Lesson.id)
        .where(
            Lesson.course_id.in_(course_ids),
            StudentProgress.student_id == student_id,
        )
        .group_by(Lesson.course_id)
    )
    completed = {
        row[0]: int(row[1] or 0)
        for row in (await db.execute(completed_stmt)).all()
    }

    out: list[EnrolledCourse] = []
    for cid, course in courses.items():
        total = totals.get(cid, 0)
        done = completed.get(cid, 0)
        pct = (done / total) if total > 0 else 0.0
        out.append(
            EnrolledCourse(
                course_id=cid,
                course_slug=course.slug,
                course_title=course.title,
                progress_pct=pct,
                total_lessons=total,
                completed_lessons=done,
                last_touched_at=last_touched_by_course.get(cid),
            )
        )
    # Most-recently-touched first.
    out.sort(
        key=lambda r: (r.last_touched_at or datetime.min),
        reverse=True,
    )
    return out


async def active_course(
    db: AsyncSession, *, student_id: uuid.UUID
) -> EnrolledCourse | None:
    """The single course the student should resume — or None if fresh."""
    rows = await list_enrolled_courses(db, student_id=student_id)
    return rows[0] if rows else None
