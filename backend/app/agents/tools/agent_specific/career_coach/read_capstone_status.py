"""D12 / Pass 3d §E.2 — read_capstone_status for career_coach.

Returns the student's active or most-recent capstone state + score
if evaluated. Read-only.

Schema fix (D12 CP3 Phase 1): exercise_submissions has no submitted_at
column; the timestamp is created_at (sibling of read_capstones bug fixed
at CP3 Part G).

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
    layer="tools.career_coach.read_capstone_status"
)


class ReadCapstoneStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose capstone to fetch.")


class CapstoneStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    exercise_title: str
    submitted: bool
    score: float | None
    feedback_summary: str | None


class ReadCapstoneStatusOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capstone: CapstoneStatus | None = None
    has_capstone: bool = False


@tool(
    name="read_capstone_status",
    description=(
        "Returns the student's most recent capstone exercise state: "
        "whether submitted, score if evaluated, and feedback summary. "
        "Used by career_coach to assess portfolio readiness."
    ),
    input_schema=ReadCapstoneStatusInput,
    output_schema=ReadCapstoneStatusOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_capstone_status(
    args: ReadCapstoneStatusInput,
) -> ReadCapstoneStatusOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_capstone_status called without an active session."
        )

    try:
        # Bug 24 fix (D15 CP3 resume): the prior LEFT JOIN-only query
        # fell through to the most-recently-authored capstone globally
        # when the student had no submissions, returning content the
        # student had no entitled access to. The fix mandates a JOIN
        # against course_entitlements (active grants only) and a role
        # filter against the student's current_role_id from
        # student_role_state. Capstones with NULL role_id (orthogonal
        # to the linear progression) remain visible — the filter only
        # excludes capstones tagged for OTHER roles. The student's
        # current_role_id is read from student_role_state at query
        # time so the tool stays single-purpose (no additional input
        # parameter).
        result = await session.execute(
            text(
                """
                SELECT
                    ex.id::text AS exercise_id,
                    ex.title AS exercise_title,
                    (es.id IS NOT NULL) AS submitted,
                    es.score,
                    es.feedback::text AS feedback_summary
                FROM exercises ex
                JOIN lessons l ON l.id = ex.lesson_id
                JOIN courses c ON c.id = l.course_id
                JOIN course_entitlements ce
                    ON ce.course_id = c.id
                    AND ce.user_id = :uid
                    AND ce.revoked_at IS NULL
                    AND (ce.expires_at IS NULL OR ce.expires_at > now())
                LEFT JOIN student_role_state srs ON srs.student_id = :uid
                LEFT JOIN exercise_submissions es
                    ON es.exercise_id = ex.id AND es.student_id = :uid
                WHERE ex.is_capstone = true
                  AND (c.role_id IS NULL OR c.role_id = srs.current_role_id)
                ORDER BY es.created_at DESC NULLS LAST, ex.created_at DESC
                LIMIT 1
                """
            ),
            {"uid": args.student_id},
        )
        row = result.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_capstone_status.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_capstone_status.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadCapstoneStatusOutput(capstone=None, has_capstone=False)

    if row is None:
        return ReadCapstoneStatusOutput(capstone=None, has_capstone=False)

    capstone = CapstoneStatus(
        exercise_id=row.exercise_id,
        exercise_title=row.exercise_title,
        submitted=bool(row.submitted),
        score=float(row.score) if row.score is not None else None,
        feedback_summary=str(row.feedback_summary)[:500] if row.feedback_summary else None,
    )
    return ReadCapstoneStatusOutput(capstone=capstone, has_capstone=True)


__all__ = [
    "CapstoneStatus",
    "ReadCapstoneStatusInput",
    "ReadCapstoneStatusOutput",
    "read_capstone_status",
]
