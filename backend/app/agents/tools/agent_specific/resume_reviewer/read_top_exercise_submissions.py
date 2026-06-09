"""D12 / Pass 3d §E.2 — read_top_exercise_submissions for resume_reviewer.

Returns the top N rated (highest score) exercise submissions. Used by
resume_reviewer to surface accomplishments the student may have
undersold on their resume.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.resume_reviewer.read_top_exercise_submissions"
)


class ReadTopSubmissionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student to fetch top submissions for.")
    top_n: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Maximum number of top submissions to return.",
    )


class TopSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    exercise_title: str
    score: float
    feedback_snippet: str | None


class ReadTopSubmissionsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissions: list[TopSubmission] = Field(default_factory=list)
    total_returned: int = Field(ge=0)


@tool(
    name="read_top_exercise_submissions",
    description=(
        "Returns the student's top N highest-scoring exercise submissions "
        "for use as evidence in resume review. Helps resume_reviewer "
        "identify accomplishments the student undersold."
    ),
    input_schema=ReadTopSubmissionsInput,
    output_schema=ReadTopSubmissionsOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_top_exercise_submissions(
    args: ReadTopSubmissionsInput,
) -> ReadTopSubmissionsOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_top_exercise_submissions called without an active session."
        )

    try:
        result = await session.execute(
            text(
                """
                SELECT
                    ex.id::text AS exercise_id,
                    ex.title AS exercise_title,
                    es.score,
                    LEFT(es.feedback::text, 400) AS feedback_snippet
                FROM exercise_submissions es
                JOIN exercises ex ON ex.id = es.exercise_id
                WHERE es.student_id = :uid
                  AND es.score IS NOT NULL
                ORDER BY es.score DESC
                LIMIT :top_n
                """
            ),
            {"uid": args.student_id, "top_n": args.top_n},
        )
        rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_top_exercise_submissions.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_top_exercise_submissions.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadTopSubmissionsOutput(submissions=[], total_returned=0)

    submissions = [
        TopSubmission(
            exercise_id=row.exercise_id,
            exercise_title=row.exercise_title,
            score=float(row.score),
            feedback_snippet=row.feedback_snippet,
        )
        for row in rows
    ]
    return ReadTopSubmissionsOutput(
        submissions=submissions, total_returned=len(submissions)
    )


__all__ = [
    "ReadTopSubmissionsInput",
    "ReadTopSubmissionsOutput",
    "TopSubmission",
    "read_top_exercise_submissions",
]
