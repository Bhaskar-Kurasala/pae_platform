"""ChatMessageFeedback model (P1-5) — thumbs up/down on an assistant turn.

Stores one row per (message_id, user_id). `rating` is a plain `String` with
a DB CHECK constraint rather than a Postgres enum — see migration 0029 for
the reasoning (matches `chat_messages.role` style, no ALTER TYPE needed to
add values later).

`reasons` is `sa.JSON` (not JSONB / ARRAY) so tests on SQLite share the same
schema as Postgres prod. The payload is a short list of enum-like strings
— we don't query into it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class ChatMessageFeedback(Base, UUIDMixin):
    __tablename__ = "chat_message_feedback"
    __table_args__ = (
        CheckConstraint(
            "rating IN ('up', 'down')",
            name="ck_chat_message_feedback_rating",
        ),
        UniqueConstraint(
            "message_id", "user_id", name="uq_chat_message_feedback_message_user"
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "rating": self.rating,
            "reasons": self.reasons,
            "comment": self.comment,
            "created_at": self.created_at,
        }
