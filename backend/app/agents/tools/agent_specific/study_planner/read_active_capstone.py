"""D12 / Pass 3d §F.3 — read_active_capstone for study_planner.

Returns capstone state and estimated remaining work so study_planner
can allocate capstone_work blocks. Read-only.

Schema fix (D12 CP3 Phase 1): exercise_submissions has no submitted_at
column; use created_at (sibling of read_capstones bug fixed at CP3 Part G).

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
    layer="tools.study_planner.read_active_capstone"
)


class ReadActiveCapstonesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose capstone to fetch.")


class ActiveCapstone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    title: str
    submitted: bool
    score: float | None
    estimated_remaining_hours: float


class ReadActiveCapstoneOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capstone: ActiveCapstone | None = None
    has_active_capstone: bool = False


@tool(
    name="read_active_capstone",
    description=(
        "Returns the student's active or most-recent capstone: "
        "submission status, score if graded, and estimated remaining "
        "work hours. Used by study_planner to allocate capstone_work "
        "blocks in weekly and session plans."
    ),
    input_schema=ReadActiveCapstonesInput,
    output_schema=ReadActiveCapstoneOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_active_capstone(
    args: ReadActiveCapstonesInput,
) -> ReadActiveCapstoneOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_active_capstone called without an active session."
        )

    try:
        result = await session.execute(
            text(
                """
                SELECT
                    ex.id::text AS exercise_id,
                    ex.title,
                    (es.id IS NOT NULL) AS submitted,
                    es.score
                FROM exercises ex
                LEFT JOIN exercise_submissions es
                    ON es.exercise_id = ex.id AND es.student_id = :uid
                WHERE ex.is_capstone = true
                ORDER BY es.created_at DESC NULLS LAST, ex.created_at DESC
                LIMIT 1
                """
            ),
            {"uid": args.student_id},
        )
        row = result.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_active_capstone.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_active_capstone.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadActiveCapstoneOutput(capstone=None, has_active_capstone=False)

    if row is None:
        return ReadActiveCapstoneOutput(capstone=None, has_active_capstone=False)

    submitted = bool(row.submitted)
    estimated_hours = 0.0 if submitted else 8.0

    capstone = ActiveCapstone(
        exercise_id=row.exercise_id,
        title=row.title,
        submitted=submitted,
        score=float(row.score) if row.score is not None else None,
        estimated_remaining_hours=estimated_hours,
    )
    return ReadActiveCapstoneOutput(capstone=capstone, has_active_capstone=True)


__all__ = [
    "ActiveCapstone",
    "ReadActiveCapstonesInput",
    "ReadActiveCapstoneOutput",
    "read_active_capstone",
]
