"""D10 Checkpoint 3 / Pass 3d §F.1 — lookup_active_entitlements.

Returns the student's currently-active course entitlements — the
authoritative "what does this student have access to right now" view.

Reads from `course_entitlements` (the table that lesson-access
middleware also reads from per the model docstring), joined with
`courses` for the slug + title the LLM will quote back to the
student.

"Active" = revoked_at IS NULL AND (expires_at IS NULL OR expires_at
> now()) — same predicate the existing entitlement_service uses
(see `_active_entitlement` in services/entitlement_service.py).

Permissions: read:student_data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.billing_support.lookup_active_entitlements"
)


class LookupActiveEntitlementsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student whose entitlements to look up."
    )


class EntitlementRecord(BaseModel):
    """One active course entitlement, projected for the LLM."""

    model_config = ConfigDict(extra="forbid")

    entitlement_id: uuid.UUID
    course_id: uuid.UUID
    course_slug: str
    course_title: str
    source: Literal["purchase", "free", "bundle", "admin_grant", "trial"]
    granted_at: datetime
    expires_at: datetime | None


class LookupActiveEntitlementsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entitlements: list[EntitlementRecord] = Field(default_factory=list)
    total_active: int = Field(
        ge=0,
        description="Length of the entitlements list.",
    )


@tool(
    name="lookup_active_entitlements",
    description=(
        "Returns the student's currently-active course entitlements "
        "— what they have access to right now. Use when the student "
        "asks 'what do I have access to', 'why can't I access X', or "
        "to confirm a course is unlocked after a payment."
    ),
    input_schema=LookupActiveEntitlementsInput,
    output_schema=LookupActiveEntitlementsOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def lookup_active_entitlements(
    args: LookupActiveEntitlementsInput,
) -> LookupActiveEntitlementsOutput:
    """Read active entitlements with a JOIN to courses for the
    course slug + title the LLM will quote back."""
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "lookup_active_entitlements called without an active session. "
            "The tool body relies on the contextvar set by call_agent."
        )

    try:
        result = await session.execute(
            sql_text(
                """
                SELECT ce.id, ce.course_id, c.slug, c.title,
                       ce.source, ce.granted_at, ce.expires_at
                FROM course_entitlements ce
                JOIN courses c ON c.id = ce.course_id
                WHERE ce.user_id = :uid
                  AND ce.revoked_at IS NULL
                  AND (ce.expires_at IS NULL OR ce.expires_at > now())
                ORDER BY ce.granted_at DESC
                """
            ),
            {"uid": args.student_id},
        )
        rows = result.all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lookup_active_entitlements.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "lookup_active_entitlements.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return LookupActiveEntitlementsOutput(entitlements=[], total_active=0)

    entitlements = [
        EntitlementRecord(
            entitlement_id=row[0],
            course_id=row[1],
            course_slug=row[2] or "",
            course_title=row[3] or "",
            source=row[4],  # type: ignore[arg-type]
            granted_at=row[5],
            expires_at=row[6],
        )
        for row in rows
    ]

    return LookupActiveEntitlementsOutput(
        entitlements=entitlements,
        total_active=len(entitlements),
    )


__all__ = [
    "EntitlementRecord",
    "LookupActiveEntitlementsInput",
    "LookupActiveEntitlementsOutput",
    "lookup_active_entitlements",
]
