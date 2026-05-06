"""D12 — lookup_base_resume for tailored_resume chat path.

Reads the student's base resume record (the one they uploaded/built in
the resume builder flow). Used by TailoredResumeAgent.run() (chat path)
to retrieve the resume to tailor.

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
    layer="tools.tailored_resume.lookup_base_resume"
)


class LookupBaseResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose base resume to fetch.")


class LookupBaseResumeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: str | None = None
    intake_data: dict[str, Any] | None = None
    verdict: str | None = None
    found: bool = False


@tool(
    name="lookup_base_resume",
    description=(
        "Returns the student's current base resume including intake data "
        "and the resume-reviewer verdict. Used by the tailored_resume "
        "chat path to retrieve the resume before delegating to the "
        "tailoring service."
    ),
    input_schema=LookupBaseResumeInput,
    output_schema=LookupBaseResumeOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def lookup_base_resume(
    args: LookupBaseResumeInput,
) -> LookupBaseResumeOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError("lookup_base_resume called without an active session.")

    try:
        result = await session.execute(
            text(
                """
                SELECT id::text AS resume_id, intake_data, verdict
                FROM resumes
                WHERE user_id = :uid
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {"uid": args.student_id},
        )
        row = result.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lookup_base_resume.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "lookup_base_resume.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return LookupBaseResumeOutput(found=False)

    if row is None:
        return LookupBaseResumeOutput(found=False)

    return LookupBaseResumeOutput(
        resume_id=row.resume_id,
        intake_data=row.intake_data,
        verdict=row.verdict,
        found=True,
    )


__all__ = [
    "LookupBaseResumeInput",
    "LookupBaseResumeOutput",
    "lookup_base_resume",
]
