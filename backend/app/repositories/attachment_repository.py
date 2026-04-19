"""ChatAttachment repository (P1-6) — pure async DB access.

Ownership checks live in the route/service layer (same pattern as
`ChatRepository`). The repo just reads + writes rows; caller owns the
transaction boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_attachment import ChatAttachment


class AttachmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_key: str,
    ) -> ChatAttachment:
        row = ChatAttachment(
            user_id=user_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def get(self, attachment_id: uuid.UUID) -> ChatAttachment | None:
        result = await self.db.execute(
            select(ChatAttachment).where(ChatAttachment.id == attachment_id)
        )
        return result.scalar_one_or_none()

    async def list_pending_for_user(
        self, user_id: uuid.UUID, ids: Sequence[uuid.UUID]
    ) -> list[ChatAttachment]:
        """Fetch all rows in `ids` that belong to `user_id` AND are still
        pending (`message_id IS NULL`). Used by the stream route to verify
        ownership and avoid double-binding an already-attached row."""
        if not ids:
            return []
        result = await self.db.execute(
            select(ChatAttachment).where(
                and_(
                    ChatAttachment.id.in_(list(ids)),
                    ChatAttachment.user_id == user_id,
                    ChatAttachment.message_id.is_(None),
                )
            )
        )
        return list(result.scalars().all())

    async def list_for_message(self, message_id: uuid.UUID) -> list[ChatAttachment]:
        result = await self.db.execute(
            select(ChatAttachment).where(ChatAttachment.message_id == message_id)
        )
        return list(result.scalars().all())

    async def bind_to_message(
        self,
        attachments: Sequence[ChatAttachment],
        message_id: uuid.UUID,
    ) -> None:
        for att in attachments:
            att.message_id = message_id
        await self.db.flush()
