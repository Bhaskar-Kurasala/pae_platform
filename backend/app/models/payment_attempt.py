"""PaymentAttempt — per-attempt transaction row against an Order.

A single Order can have multiple attempts (e.g. first card declined, user
retries with a different card). Each attempt carries the provider's payment
id, the verified signature, and the raw provider response for forensics.

Status: created → authorized → captured → failed.
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

ATTEMPT_STATUS_CREATED = "created"
ATTEMPT_STATUS_AUTHORIZED = "authorized"
ATTEMPT_STATUS_CAPTURED = "captured"
ATTEMPT_STATUS_FAILED = "failed"

ATTEMPT_STATUSES = {
    ATTEMPT_STATUS_CREATED,
    ATTEMPT_STATUS_AUTHORIZED,
    ATTEMPT_STATUS_CAPTURED,
    ATTEMPT_STATUS_FAILED,
}


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    provider_signature: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ATTEMPT_STATUS_CREATED
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
