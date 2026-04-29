"""F11 — RefundOffer: admin-reviewed refund proposals for paid_silent students.

Slip 4 (paid_silent) crossing day 14 is the worst-case combination — paid +
not engaging — and historically the highest refund-request volume. Rather
than wait for the student to write asking for one, the admin offers it
proactively. This table audits every such offer: who proposed, who got it,
how the student responded, and when.

One row per (user_id, proposed_at). Multiple offers per user are legal —
the spec doesn't constrain reissuing — but in practice the admin should
treat a 'declined' or 'accepted' as terminal.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class RefundOffer(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "refund_offers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 'proposed' | 'sent' | 'accepted' | 'declined' | 'expired'.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    outreach_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_log.id", ondelete="SET NULL"),
        nullable=True,
    )
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
