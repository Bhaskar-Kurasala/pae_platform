"""D12 — lookup_jd_decoded for tailored_resume chat path.

Reads a previously decoded JD from the JD decoder service output.
Used by TailoredResumeAgent.run() (chat path) to retrieve JD text
that the student has already pasted, if a jd_id was provided.

Falls back gracefully when no jd_id is available — the agent then
uses the raw jd_text from input directly.

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
    layer="tools.tailored_resume.lookup_jd_decoded"
)


class LookupJdDecodedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jd_id: uuid.UUID = Field(description="ID of a previously decoded JD.")
    # D17b/ITEM 2.C — owner check. The previous SQL was
    # `WHERE jd_id = :jd_id LIMIT 1` with no user scoping; any caller
    # with a jd_id could read any student's tailored_resumes row.
    # Caller passes ctx.user_id; SQL gates `AND user_id = :student_id`.
    # Mismatched ownership returns found=False (single error mode —
    # same shape as "JD not found" so existence isn't probable).
    #
    # Note: as of D17b/CP3.2 pre-flight audit, no agent code path
    # actually invokes this tool — tailored_resume_v2 fetches the
    # JD via the service path generate_tailored_resume(jd_id=...)
    # in tailored_resume_service.py, not via this tool. The tool is
    # registered and reachable via the LLM tool-use protocol; the
    # fix is defense-in-depth before someone wires it up.
    student_id: uuid.UUID = Field(
        description=(
            "The student the agent is acting on behalf of (typically "
            "ctx.user_id). The tool returns found=False if the JD is "
            "not owned by this student — closes the cross-student JD "
            "leak vector flagged in d12-d14c-read-tool-entitlement-"
            "leakage-audit (MEDIUM finding, D17b/ITEM 2.C)."
        ),
    )


class LookupJdDecodedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jd_text: str | None = None
    jd_parsed: dict[str, Any] | None = None
    found: bool = False


@tool(
    name="lookup_jd_decoded",
    description=(
        "Reads a decoded JD by ID. Used by the tailored_resume chat path "
        "when the student provided a jd_id from a prior JD parsing step."
    ),
    input_schema=LookupJdDecodedInput,
    output_schema=LookupJdDecodedOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def lookup_jd_decoded(args: LookupJdDecodedInput) -> LookupJdDecodedOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError("lookup_jd_decoded called without an active session.")

    try:
        result = await session.execute(
            text(
                "SELECT jd_text, jd_parsed FROM tailored_resumes "
                "WHERE jd_id = :jd_id AND user_id = :student_id "
                "LIMIT 1"
            ),
            {"jd_id": args.jd_id, "student_id": args.student_id},
        )
        row = result.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lookup_jd_decoded.query_failed",
            error=str(exc),
            jd_id=str(args.jd_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "lookup_jd_decoded.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
            )
        return LookupJdDecodedOutput(found=False)

    if row is None:
        return LookupJdDecodedOutput(found=False)

    return LookupJdDecodedOutput(
        jd_text=row.jd_text,
        jd_parsed=row.jd_parsed,
        found=True,
    )


__all__ = [
    "LookupJdDecodedInput",
    "LookupJdDecodedOutput",
    "lookup_jd_decoded",
]
