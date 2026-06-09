"""D12 / Pass 3d §E.2 — read_student_full_progress for career_coach.

Returns consolidated progress across all enrolled courses: lessons
completed, exercise submission scores, overall completion percentages.
Read-only; no writes.

Schema fixes (D12 CP3 Phase 1):
  • student_progress.completed → completed_at IS NOT NULL (no `completed` column).
  • exercises.course_id alias is invalid; route via lessons.course_id instead
    (exercises link to lessons, lessons to courses).

Permissions: read:student_data
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.career_coach.read_student_full_progress"
)


class ReadStudentFullProgressInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose progress to fetch.")


class CourseProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_title: str
    completion_pct: float
    lessons_completed: int
    lessons_total: int
    avg_exercise_score: float | None


class ReadStudentFullProgressOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courses: list[CourseProgress] = Field(default_factory=list)
    total_lessons_completed: int = Field(ge=0)
    total_exercise_submissions: int = Field(ge=0)
    overall_avg_score: float | None = None


@tool(
    name="read_student_full_progress",
    description=(
        "Returns a student's consolidated progress across all enrolled "
        "courses: completion percentages, lessons completed, and average "
        "exercise scores per course. Used by career_coach to ground "
        "plan recommendations in actual progress data."
    ),
    input_schema=ReadStudentFullProgressInput,
    output_schema=ReadStudentFullProgressOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def read_student_full_progress(
    args: ReadStudentFullProgressInput,
) -> ReadStudentFullProgressOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_student_full_progress called without an active session."
        )

    try:
        result = await session.execute(
            text(
                """
                SELECT
                    c.id::text AS course_id,
                    c.title AS course_title,
                    COALESCE(e.progress_pct, 0.0) AS completion_pct,
                    COUNT(DISTINCT sp.lesson_id) FILTER (WHERE sp.completed_at IS NOT NULL) AS lessons_completed,
                    COUNT(DISTINCT l.id) AS lessons_total,
                    AVG(es.score) AS avg_exercise_score
                FROM enrollments e
                JOIN courses c ON c.id = e.course_id
                LEFT JOIN lessons l ON l.course_id = c.id
                LEFT JOIN student_progress sp
                    ON sp.lesson_id = l.id AND sp.student_id = e.student_id
                LEFT JOIN exercises ex
                    ON ex.lesson_id = l.id
                LEFT JOIN exercise_submissions es
                    ON es.exercise_id = ex.id AND es.student_id = e.student_id
                WHERE e.student_id = :uid
                GROUP BY c.id, c.title, e.progress_pct
                ORDER BY c.title
                """
            ),
            {"uid": args.student_id},
        )
        rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_student_full_progress.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_student_full_progress.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadStudentFullProgressOutput(
            courses=[],
            total_lessons_completed=0,
            total_exercise_submissions=0,
        )

    courses: list[CourseProgress] = []
    total_completed = 0
    for row in rows:
        cp = CourseProgress(
            course_id=row.course_id,
            course_title=row.course_title,
            completion_pct=float(row.completion_pct or 0.0),
            lessons_completed=int(row.lessons_completed or 0),
            lessons_total=int(row.lessons_total or 0),
            avg_exercise_score=(
                float(row.avg_exercise_score) if row.avg_exercise_score is not None else None
            ),
        )
        courses.append(cp)
        total_completed += cp.lessons_completed

    scores = [c.avg_exercise_score for c in courses if c.avg_exercise_score is not None]
    overall_avg = sum(scores) / len(scores) if scores else None

    return ReadStudentFullProgressOutput(
        courses=courses,
        total_lessons_completed=total_completed,
        total_exercise_submissions=0,
        overall_avg_score=overall_avg,
    )


__all__ = [
    "CourseProgress",
    "ReadStudentFullProgressInput",
    "ReadStudentFullProgressOutput",
    "read_student_full_progress",
]
