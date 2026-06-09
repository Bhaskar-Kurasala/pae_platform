"""ReadinessActionCompletion — memory of cleared "top-3 next actions".

The Overview view ranks suggested next actions from real signals
(weakness ledger, resume freshness, JD library, etc.). This table records
which suggestions a user has already acted on so the same nag doesn't
resurface during the cooldown window.

Idempotent on `(user_id, action_kind, payload_hash)`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReadinessActionCompletion(Base):
    __tablename__ = "readiness_action_completions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "action_kind",
            "payload_hash",
            name="uq_readiness_action_completion",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # Stable hash of the payload so re-completions don't duplicate.
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
