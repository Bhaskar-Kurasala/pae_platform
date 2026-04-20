"""ChatMessage model — one turn (user / assistant / system) in a conversation.

`role` is constrained at the application layer (see `app.schemas.chat`). We
deliberately keep the column as a plain `String` rather than a DB-level enum
so we can add roles later (e.g. 'tool') without a migration.

`parent_id` is a self-FK that stays NULL for v1; it's here now so the future
branching feature (P1-3) doesn't need another schema migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDMixin

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class ChatMessage(Base, UUIDMixin):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index(
            "ix_chat_messages_conversation_id_created_at",
            "conversation_id",
            "created_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # P2-5 — hover-panel metadata stamped by the stream endpoint. Every
    # column is nullable so historical rows / stream-error paths / missing
    # provider usage data render as "—" in the UI instead of breaking.
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # P1-3 forward-compat: nullable self-FK for branching. No relationship
    # defined yet — the tree traversal lands with that ticket.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    # P1-1 — soft-delete marker. When an edit truncates a conversation we
    # stamp downstream rows with `deleted_at` rather than hard-deleting, so
    # analytics retains the full transcript + audit trail. Repository
    # queries filter `deleted_at IS NOT NULL` out by default; an explicit
    # `include_deleted=True` surfaces them.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
