"""Conversation model — persistent chat thread owned by a user.

A conversation groups an ordered stream of `ChatMessage` rows. It stores the
routed agent name (may change per-turn but the first-turn routing is captured
at creation), a human-readable title (auto-derived from the first user message),
and a nullable `archived_at` so users can soft-archive without losing the
thread.

Hard-deletion on the conversation cascades to its messages (see
`chat_messages.conversation_id` FK `ondelete=CASCADE`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class Conversation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # P1-8 — `pinned_at` (nullable timestamp) rather than a boolean so the
    # sidebar can sort pinned threads by pin-time without a second column.
    # `ORDER BY pinned_at DESC NULLS LAST, updated_at DESC` surfaces the
    # most-recently-pinned first, then falls back to recency for unpinned
    # rows. Setting to NULL on unpin (see `ChatRepository.set_pinned`).
    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # `passive_deletes=False` so SQLAlchemy issues an explicit DELETE for each
    # child row on `session.delete(conv)` — guarantees cascade even on engines
    # that don't enforce FK cascades at the DB level (SQLite in tests without
    # `PRAGMA foreign_keys=ON`). Postgres gets a belt-and-braces: the ORM
    # emits the child DELETE, and `ondelete=CASCADE` on `chat_messages` would
    # also fire if the ORM path were ever bypassed.
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=False,
        lazy="select",
    )


from app.models.chat_message import ChatMessage  # noqa: E402
