"""NotebookEntry model (P3-4) — student-saved assistant messages.

One row per bookmark: the student taps the bookmark icon on an assistant
bubble and the message content + ids are written here. Soft-dedup is
intentional — the same message can be bookmarked multiple times (e.g.
different titles/tags on each save).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class NotebookEntry(Base, UUIDMixin):
    __tablename__ = "notebook_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # message_id / conversation_id stored as plain strings — notebook entries
    # outlive the source chat (no FK, so chat deletion never cascades here).
    message_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Student's own annotation — transforms "AI said X" → "I learned X"
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where this note came from: "chat" | "quiz" | "interview" | "career"
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True, default="chat")
    # Topic / course context passed from the UI at save time
    topic: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Spaced-review tracking — NULL means never reviewed
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "content": self.content,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
