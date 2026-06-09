"""Order — user's intent to buy a course or bundle (Catalog refactor 2026-04-26).

State machine: created → authorized → paid → fulfilled → failed → refunded.

Holds the provider's order id (e.g. Razorpay `order_xyz`) so the webhook
can route an event back to the right row, plus a generated receipt number,
optional GST breakdown for India invoices, and a JSON metadata bag for
provider-specific fields without forcing schema migrations.

Distinct from `payments`: an order is the user's INTENT. The actual money
movement lives in `payment_attempts` so we can model declined-card-then-
retry without losing the order context.
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

# Status values — kept here as the canonical enum so services + tests can
# import a single source of truth.
ORDER_STATUS_CREATED = "created"
ORDER_STATUS_AUTHORIZED = "authorized"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_FULFILLED = "fulfilled"
ORDER_STATUS_FAILED = "failed"
ORDER_STATUS_REFUNDED = "refunded"

ORDER_STATUSES = {
    ORDER_STATUS_CREATED,
    ORDER_STATUS_AUTHORIZED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_FULFILLED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_REFUNDED,
}

# Target type — what the order grants entitlement to.
TARGET_COURSE = "course"
TARGET_BUNDLE = "bundle"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="INR"
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ORDER_STATUS_CREATED
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(
        String(40), nullable=True, unique=True
    )
    gst_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(
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
