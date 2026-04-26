"""Refund — money returned to the user against an Order.

Created either by an admin call or by a provider-initiated refund webhook.
On `processed` status, the linked entitlement is revoked (revoked_at set).

Status: pending → processed → failed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

REFUND_STATUS_PENDING = "pending"
REFUND_STATUS_PROCESSED = "processed"
REFUND_STATUS_FAILED = "failed"

REFUND_STATUSES = {
    REFUND_STATUS_PENDING,
    REFUND_STATUS_PROCESSED,
    REFUND_STATUS_FAILED,
}


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payment_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="INR"
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=REFUND_STATUS_PENDING
    )
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
