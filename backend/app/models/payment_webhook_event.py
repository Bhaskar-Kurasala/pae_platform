"""PaymentWebhookEvent — append-only ledger for incoming provider webhooks.

Razorpay (and Stripe) retry webhooks up to 5×. Without dedup we'd grant
entitlements N times. This table is the dedup boundary: every webhook
INSERTs here BEFORE any business logic runs, keyed UNIQUE on
(provider, provider_event_id). A duplicate insert raises IntegrityError
and the handler short-circuits cleanly.

raw_body is kept as bytes (Postgres BYTEA) so we can re-verify signatures
later if a secret is rotated and we need to backfill.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_payment_webhook_provider_event",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    signature: Mapped[str | None] = mapped_column(String(512), nullable=True)
    signature_valid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    related_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
