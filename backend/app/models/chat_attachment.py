"""ChatAttachment model (P1-6) — a file/image attached to a chat turn.

Rows are created with `message_id = NULL` on upload (the attachment is
"pending"), then bound to the user's message row when the student hits send
and the stream endpoint persists their turn. `user_id` is always set so we
can enforce ownership before binding.

`storage_key` is opaque to the DB — it's whatever the `AttachmentStorage`
backend chooses. Today that's a local-fs path under
`settings.attachments_dir`; in prod it will be an S3 object key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class ChatAttachment(Base, UUIDMixin):
    __tablename__ = "chat_attachments"

    # Nullable until the attachment is bound to a persisted user message.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
