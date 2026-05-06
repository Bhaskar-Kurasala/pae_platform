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
                "WHERE jd_id = :jd_id LIMIT 1"
            ),
            {"jd_id": args.jd_id},
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
