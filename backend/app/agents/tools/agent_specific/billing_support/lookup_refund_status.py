"""D10 Checkpoint 3 / Pass 3d §F.1 — lookup_refund_status.

Returns refund-state-machine status for a specific order or all of
the student's orders. Reads from `refunds` joined with `orders` so
the caller can correlate by receipt number; also surfaces the
status of the original `payment_attempts` row when relevant
(e.g., "the original payment is still in 'authorized' state, refund
will fire after capture settles").

Refund status flow per the model: pending → processed → failed.

Permissions: read:student_data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.billing_support.lookup_refund_status"
)


class LookupRefundStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student whose refund(s) to look up."
    )
    order_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional: scope to refunds for one order. None returns "
            "all refunds for the student across all their orders."
        ),
    )


class RefundRecord(BaseModel):
    """One refund row, projected for the LLM."""

    model_config = ConfigDict(extra="forbid")

    refund_id: uuid.UUID
    order_id: uuid.UUID
    receipt_number: str | None
    amount: Decimal
    currency: str
    status: Literal["pending", "processed", "failed"]
    reason: str | None
    provider: str
    provider_refund_id: str | None
    created_at: datetime
    processed_at: datetime | None
    # Original payment attempt status (e.g. "captured" / "authorized")
    # surfaced so the LLM can explain "your charge captured, refund
    # is processing" vs "your charge is still authorizing, the refund
    # will fire after settlement". Null when refund isn't linked to
    # a specific attempt.
    payment_attempt_status: str | None


class LookupRefundStatusOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refunds: list[RefundRecord] = Field(default_factory=list)
    total_returned: int = Field(ge=0)


@tool(
    name="lookup_refund_status",
    description=(
        "Returns refund state-machine status for a specific order "
        "(if order_id given) or all of the student's refunds. Use "
        "when the student asks 'where is my refund', 'why hasn't my "
        "card been credited', or to confirm a refund was processed."
    ),
    input_schema=LookupRefundStatusInput,
    output_schema=LookupRefundStatusOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def lookup_refund_status(
    args: LookupRefundStatusInput,
) -> LookupRefundStatusOutput:
    """Read refunds via raw SQL + LEFT JOIN to payment_attempts so
    we can surface the original attempt's status.

    The query is scoped through the orders table to enforce that
    the refund actually belongs to this student (SECURITY: never
    return another student's refund records — the join through
    orders.user_id = :uid is the gate).
    """
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "lookup_refund_status called without an active session. "
            "The tool body relies on the contextvar set by call_agent."
        )

    # Build the WHERE filter: always scope by user_id (security);
    # optionally narrow to a single order_id.
    where_clauses = ["o.user_id = :uid"]
    params: dict[str, object] = {"uid": args.student_id}
    if args.order_id is not None:
        where_clauses.append("r.order_id = :oid")
        params["oid"] = args.order_id

    where_sql = " AND ".join(where_clauses)

    try:
        result = await session.execute(
            sql_text(
                f"""
                SELECT r.id, r.order_id, o.receipt_number,
                       r.amount_cents, r.currency, r.status,
                       r.reason, r.provider, r.provider_refund_id,
                       r.created_at, r.processed_at,
                       pa.status AS payment_attempt_status
                FROM refunds r
                JOIN orders o ON o.id = r.order_id
                LEFT JOIN payment_attempts pa
                  ON pa.id = r.payment_attempt_id
                WHERE {where_sql}
                ORDER BY r.created_at DESC
                """
            ),
            params,
        )
        rows = result.all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lookup_refund_status.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
            order_id=str(args.order_id) if args.order_id else None,
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "lookup_refund_status.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return LookupRefundStatusOutput(refunds=[], total_returned=0)

    refunds = [
        RefundRecord(
            refund_id=row[0],
            order_id=row[1],
            receipt_number=row[2],
            amount=Decimal(row[3]) / Decimal(100),
            currency=row[4],
            status=row[5],  # type: ignore[arg-type]
            reason=row[6],
            provider=row[7],
            provider_refund_id=row[8],
            created_at=row[9],
            processed_at=row[10],
            payment_attempt_status=row[11],
        )
        for row in rows
    ]

    return LookupRefundStatusOutput(
        refunds=refunds,
        total_returned=len(refunds),
    )


__all__ = [
    "LookupRefundStatusInput",
    "LookupRefundStatusOutput",
    "RefundRecord",
    "lookup_refund_status",
]
