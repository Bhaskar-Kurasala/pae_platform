"""D10 Checkpoint 3 / Pass 3d §F.1 — lookup_order_history.

Returns the student's orders, most-recent first, with the fields the
billing_support prompt needs to ground its answers (receipt number,
amount, status, paid_at, etc.).

Reads from `orders` (Catalog refactor 2026-04-26 / migration 0047_payments_v2).
The receipt_number field is what students see on their receipts —
e.g., "CF-20260415-A8K2" (CareerForge legacy era) or "AC-..." (new
AICareerOS receipts going forward, per Pass 3j brand sweep).

Permissions: read:student_data — the agent's own
`uses_memory=True` + permission set from AgenticBaseAgent already
grants this in production; the executor checks it before
dispatching.
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

log = structlog.get_logger().bind(layer="tools.billing_support.lookup_order_history")


class LookupOrderHistoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student whose orders to look up."
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum orders to return (most-recent first).",
    )


class OrderRecord(BaseModel):
    """One order row, projected to fields the LLM needs.

    `amount` is rendered as a Decimal in INR (the source column is
    amount_cents — converted here). `currency` always set so the LLM
    doesn't have to assume.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: uuid.UUID
    receipt_number: str | None
    target_type: Literal["course", "bundle"]
    target_id: uuid.UUID
    amount: Decimal
    currency: str
    status: str
    provider: str
    paid_at: datetime | None
    fulfilled_at: datetime | None
    created_at: datetime


class LookupOrderHistoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orders: list[OrderRecord] = Field(default_factory=list)
    total_returned: int = Field(
        ge=0,
        description="Length of the orders list (== len(orders)).",
    )
    truncated: bool = Field(
        description=(
            "True iff there are more orders for this student than "
            "the limit allowed; the agent should mention this to the "
            "student rather than implying they have only N orders."
        ),
    )


@tool(
    name="lookup_order_history",
    description=(
        "Returns the student's orders, most-recent first. Use when "
        "the student asks about a specific order, a charge they "
        "don't recognize, or to confirm what they've paid for. "
        "Always prefer real lookups over guessing at receipt numbers."
    ),
    input_schema=LookupOrderHistoryInput,
    output_schema=LookupOrderHistoryOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def lookup_order_history(
    args: LookupOrderHistoryInput,
) -> LookupOrderHistoryOutput:
    """Read recent orders via raw SQL (avoids loading the ORM model
    + relationships we don't need)."""
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "lookup_order_history called without an active session. "
            "The tool body relies on the contextvar set by call_agent."
        )

    try:
        # Pull limit+1 so we can detect truncation cheaply.
        result = await session.execute(
            sql_text(
                """
                SELECT id, receipt_number, target_type, target_id,
                       amount_cents, currency, status, provider,
                       paid_at, fulfilled_at, created_at
                FROM orders
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :limit_plus_one
                """
            ),
            {"uid": args.student_id, "limit_plus_one": args.limit + 1},
        )
        rows = result.all()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lookup_order_history.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        # asyncpg-rollback discipline per
        # docs/followups/asyncpg-rollback-discipline.md
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "lookup_order_history.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return LookupOrderHistoryOutput(
            orders=[], total_returned=0, truncated=False
        )

    truncated = len(rows) > args.limit
    rows_to_return = rows[: args.limit]

    orders = [
        OrderRecord(
            order_id=row[0],
            receipt_number=row[1],
            target_type=row[2],  # type: ignore[arg-type]
            target_id=row[3],
            # amount_cents → INR Decimal (currency in row[5]; we
            # don't currency-convert here — the column already names
            # the currency).
            amount=Decimal(row[4]) / Decimal(100),
            currency=row[5],
            status=row[6],
            provider=row[7],
            paid_at=row[8],
            fulfilled_at=row[9],
            created_at=row[10],
        )
        for row in rows_to_return
    ]

    return LookupOrderHistoryOutput(
        orders=orders,
        total_returned=len(orders),
        truncated=truncated,
    )


__all__ = [
    "LookupOrderHistoryInput",
    "LookupOrderHistoryOutput",
    "OrderRecord",
    "lookup_order_history",
]
