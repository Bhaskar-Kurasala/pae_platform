"""D12 / Pass 3d §E.2 — read_capstones for resume_reviewer.

Returns all capstone exercises the student has submitted, with scores
and feedback, so resume_reviewer can cross-reference resume claims
against actual completed capstones. Orders by created_at (the real
timestamp on exercise_submissions; submitted_at never existed —
D12 CP3 Part G).

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
    layer="tools.resume_reviewer.read_capstones"
)


class ReadCapstonesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose capstones to fetch.")


class CapstoneSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    title: str
    score: float | None
    feedback_snippet: str | None


class ReadCapstonesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capstones: list[CapstoneSubmission] = Field(default_factory=list)
    total: int = Field(ge=0)


@tool(
    name="read_capstones",
    description=(
        "Returns all capstone exercises submitted by this student, "
        "including scores and feedback. Used by resume_reviewer to "
        "cross-reference resume claims against actual completed "
        "capstones and ground unsupported-claim detection."
    ),
    input_schema=ReadCapstonesInput,
    output_schema=ReadCapstonesOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_capstones(args: ReadCapstonesInput) -> ReadCapstonesOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError("read_capstones called without an active session.")

    try:
        result = await session.execute(
            text(
                """
                SELECT
                    ex.id::text AS exercise_id,
                    ex.title,
                    es.score,
                    LEFT(es.feedback::text, 400) AS feedback_snippet
                FROM exercises ex
                JOIN exercise_submissions es
                    ON es.exercise_id = ex.id AND es.student_id = :uid
                WHERE ex.is_capstone = true
                ORDER BY es.created_at DESC
                """
            ),
            {"uid": args.student_id},
        )
        rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_capstones.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_capstones.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadCapstonesOutput(capstones=[], total=0)

    capstones = [
        CapstoneSubmission(
            exercise_id=row.exercise_id,
            title=row.title,
            score=float(row.score) if row.score is not None else None,
            feedback_snippet=row.feedback_snippet,
        )
        for row in rows
    ]
    return ReadCapstonesOutput(capstones=capstones, total=len(capstones))


__all__ = [
    "CapstoneSubmission",
    "ReadCapstonesInput",
    "ReadCapstonesOutput",
    "read_capstones",
]
