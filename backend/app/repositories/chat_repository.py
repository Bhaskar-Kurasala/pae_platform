"""Chat persistence repository (P0-2).

Thin async-SQLAlchemy data access for `Conversation` and `ChatMessage`. The
repository does NOT do ownership checks — those belong in
`app.services.chat_service` so the route layer gets a uniform 404 when a
caller asks for someone else's row.

Caller owns the transaction: we `await flush()` so callers can chain reads
before their outer commit, but never `commit()` ourselves.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat_feedback import ChatMessageFeedback
from app.models.chat_message import ChatMessage
from app.models.conversation import Conversation


class ChatRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- conversations ----------------------------------------------------

    async def create_conversation(
        self,
        *,
        user_id: uuid.UUID,
        agent_name: str | None = None,
        title: str | None = None,
    ) -> Conversation:
        conv = Conversation(user_id=user_id, agent_name=agent_name, title=title)
        self.db.add(conv)
        await self.db.flush()
        await self.db.refresh(conv)
        return conv

    async def get_conversation(
        self, conversation_id: uuid.UUID, *, with_messages: bool = False
    ) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        if with_messages:
            stmt = stmt.options(selectinload(Conversation.messages))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_conversations_for_user(
        self,
        user_id: uuid.UUID,
        *,
        include_archived: bool = False,
        search: str | None = None,
        limit: int = 100,
    ) -> list[tuple[Conversation, int]]:
        """Return (conversation, message_count) pairs, newest-first.

        Uses a LEFT JOIN + GROUP BY so a conversation without messages still
        appears with `message_count = 0`. Soft-deleted rows (P1-1
        `deleted_at IS NOT NULL`) are excluded from the count so the sidebar
        displays the current, user-visible message count.
        """
        count_col = func.count(ChatMessage.id)
        # P1-8 — pinned rows float to the top. `pinned_at DESC` naturally
        # puts NULLs last on Postgres (and on SQLite's default NULL
        # ordering for DESC), so a single ORDER BY gives pinned-first +
        # chronologically-fresh-next without a UNION or a CASE expression.
        stmt = (
            select(Conversation, count_col)
            .outerjoin(
                ChatMessage,
                and_(
                    ChatMessage.conversation_id == Conversation.id,
                    ChatMessage.deleted_at.is_(None),
                ),
            )
            .where(Conversation.user_id == user_id)
            .group_by(Conversation.id)
            .order_by(
                Conversation.pinned_at.desc(),
                Conversation.updated_at.desc(),
            )
            .limit(limit)
        )
        if not include_archived:
            stmt = stmt.where(Conversation.archived_at.is_(None))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Conversation.title.ilike(pattern),
                    # Also search message content — the sidebar search feature
                    # (P1-8) expects content-level hits. Cheap enough for v1
                    # with Postgres ILIKE on a small per-user row set.
                    # Exclude soft-deleted rows so students can't re-surface
                    # an edited-away turn via search.
                    Conversation.id.in_(
                        select(ChatMessage.conversation_id).where(
                            and_(
                                ChatMessage.content.ilike(pattern),
                                ChatMessage.deleted_at.is_(None),
                            )
                        )
                    ),
                )
            )
        result = await self.db.execute(stmt)
        return [(row[0], int(row[1])) for row in result.all()]

    async def update_conversation(
        self,
        conversation: Conversation,
        *,
        title: str | None = None,
        archived: bool | None = None,
        pinned: bool | None = None,
    ) -> Conversation:
        if title is not None:
            conversation.title = title
        if archived is not None:
            conversation.archived_at = datetime.now(UTC) if archived else None
        if pinned is not None:
            # P1-8 — tri-state: True stamps now(), False clears. Keeping the
            # stamp (rather than a boolean column) preserves pin-order in
            # the sidebar list query.
            conversation.pinned_at = datetime.now(UTC) if pinned else None
        await self.db.flush()
        await self.db.refresh(conversation)
        return conversation

    async def soft_archive_conversation(
        self, conversation: Conversation
    ) -> Conversation:
        conversation.archived_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(conversation)
        return conversation

    async def delete_conversation(self, conversation_id: uuid.UUID) -> bool:
        """Hard-delete. Uses the ORM delete path (rather than a bulk DELETE)
        so the relationship's `cascade="all, delete-orphan"` fires — that
        way child messages go even when the underlying engine doesn't
        enforce FK cascades (SQLite without `PRAGMA foreign_keys=ON`).
        Postgres additionally enforces `ondelete=CASCADE` at the DB level."""
        conv = await self.get_conversation(conversation_id)
        if conv is None:
            return False
        await self.db.delete(conv)
        await self.db.flush()
        return True

    async def touch_conversation(self, conversation: Conversation) -> None:
        """Bump `updated_at` to now. SQLAlchemy's `onupdate` only fires on
        column-level changes, so we write the field explicitly."""
        conversation.updated_at = datetime.now(UTC)
        await self.db.flush()

    # --- messages ---------------------------------------------------------

    async def add_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        agent_name: str | None = None,
        token_count: int | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> ChatMessage:
        msg = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            agent_name=agent_name,
            token_count=token_count,
            parent_id=parent_id,
        )
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        *,
        limit: int = 50,
        before: uuid.UUID | None = None,
        ascending: bool = True,
        include_deleted: bool = False,
    ) -> list[ChatMessage]:
        """Ordered message fetch. `before` is a cursor — when provided, the
        result only includes messages strictly older than the cursor's
        `created_at`, which is the classic newest-first pagination shape. The
        return order is controlled by `ascending` (True = chronological,
        which is what the chat UI consumes).

        P1-1: soft-deleted rows (`deleted_at IS NOT NULL`) are excluded by
        default. Pass `include_deleted=True` from admin/analytics paths that
        need the full audit trail.
        """
        stmt = select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id
        )
        if not include_deleted:
            stmt = stmt.where(ChatMessage.deleted_at.is_(None))
        if before is not None:
            cursor = await self.db.execute(
                select(ChatMessage.created_at).where(ChatMessage.id == before)
            )
            cursor_ts = cursor.scalar_one_or_none()
            if cursor_ts is not None:
                stmt = stmt.where(
                    and_(
                        ChatMessage.created_at < cursor_ts,
                        ChatMessage.id != before,
                    )
                )

        if ascending:
            # When paginating backwards we still want to return ascending
            # chronological order to the caller, so we fetch descending + flip.
            stmt_desc = stmt.order_by(ChatMessage.created_at.desc()).limit(limit)
            result = await self.db.execute(stmt_desc)
            rows = list(result.scalars().all())
            rows.reverse()
            return rows

        result = await self.db.execute(
            stmt.order_by(ChatMessage.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def count_messages(
        self,
        conversation_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> int:
        stmt = select(func.count(ChatMessage.id)).where(
            ChatMessage.conversation_id == conversation_id
        )
        if not include_deleted:
            stmt = stmt.where(ChatMessage.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_message(
        self,
        message_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> ChatMessage | None:
        stmt = select(ChatMessage).where(ChatMessage.id == message_id)
        if not include_deleted:
            stmt = stmt.where(ChatMessage.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_siblings(
        self, parent_message_id: uuid.UUID
    ) -> list[ChatMessage]:
        """P1-2 — assistant messages that share a user parent.

        Returns ALL assistant children of `parent_message_id` (the user turn)
        ordered by `created_at` ascending. Soft-deleted rows are filtered out
        so the sibling navigator reflects only live versions.
        """
        result = await self.db.execute(
            select(ChatMessage)
            .where(
                and_(
                    ChatMessage.parent_id == parent_message_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.deleted_at.is_(None),
                )
            )
            .order_by(ChatMessage.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_sibling_map(
        self, parent_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """P1-2 — bulk fetch of `{parent_id: [sibling_ids...]}` for a set of
        user message ids. Used by the conversation GET path to inline
        `sibling_ids` on each assistant message in a single query."""
        if not parent_ids:
            return {}
        result = await self.db.execute(
            select(
                ChatMessage.parent_id,
                ChatMessage.id,
                ChatMessage.created_at,
            )
            .where(
                and_(
                    ChatMessage.parent_id.in_(parent_ids),
                    ChatMessage.role == "assistant",
                    ChatMessage.deleted_at.is_(None),
                )
            )
            .order_by(ChatMessage.created_at.asc())
        )
        out: dict[uuid.UUID, list[uuid.UUID]] = {}
        for parent_id, msg_id, _ in result.all():
            if parent_id is None:
                continue
            out.setdefault(parent_id, []).append(msg_id)
        return out

    async def get_messages_for_regenerate(
        self,
        conversation_id: uuid.UUID,
        cutoff_user_message_id: uuid.UUID,
    ) -> list[ChatMessage]:
        """P1-2 — history slice used when regenerating an assistant reply.

        Returns every non-deleted message in the conversation whose
        `created_at` is less than or equal to the cutoff user message, in
        ascending chronological order. Assistant messages created AFTER the
        cutoff — later turns, or newer variants — are excluded so the LLM
        sees only the history up to and including the user turn being
        regenerated.
        """
        cursor_result = await self.db.execute(
            select(ChatMessage.created_at).where(
                ChatMessage.id == cutoff_user_message_id
            )
        )
        cutoff_ts = cursor_result.scalar_one_or_none()
        if cutoff_ts is None:
            return []

        stmt = (
            select(ChatMessage)
            .where(
                and_(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.created_at <= cutoff_ts,
                    ChatMessage.deleted_at.is_(None),
                )
            )
            .order_by(ChatMessage.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def soft_delete_messages_from(
        self,
        conversation_id: uuid.UUID,
        *,
        from_created_at: datetime,
    ) -> int:
        """P1-1 — stamp `deleted_at = now()` on every message in the
        conversation whose `created_at >= from_created_at` that isn't already
        soft-deleted. Returns the number of rows affected.

        Uses a plain `SELECT ... FOR UPDATE`-free loop over the ORM so the
        relationship cache stays consistent (bulk `UPDATE` would leave the
        already-loaded `Conversation.messages` collection stale). Volume here
        is bounded by one conversation's length, so the O(N) cost is fine.
        """
        now = datetime.now(UTC)
        stmt = select(ChatMessage).where(
            and_(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.created_at >= from_created_at,
                ChatMessage.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            row.deleted_at = now
        await self.db.flush()
        return len(rows)

    # --- feedback (P1-5) --------------------------------------------------

    async def get_feedback_for_user(
        self, message_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatMessageFeedback | None:
        result = await self.db.execute(
            select(ChatMessageFeedback).where(
                and_(
                    ChatMessageFeedback.message_id == message_id,
                    ChatMessageFeedback.user_id == user_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert_feedback(
        self,
        *,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        rating: str,
        reasons: list[str] | None,
        comment: str | None,
    ) -> ChatMessageFeedback:
        """Insert-or-update semantics on (message_id, user_id).

        We do a fetch → mutate-or-create rather than a dialect-specific
        `ON CONFLICT` so the same code path works on both Postgres (prod)
        and SQLite (tests). The unique constraint at the DB level is
        belt-and-braces against a concurrent race.
        """
        existing = await self.get_feedback_for_user(message_id, user_id)
        if existing is not None:
            existing.rating = rating
            existing.reasons = reasons
            existing.comment = comment
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        row = ChatMessageFeedback(
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            reasons=reasons,
            comment=comment,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def get_feedback_for_message_ids(
        self, message_ids: list[uuid.UUID], user_id: uuid.UUID
    ) -> dict[uuid.UUID, ChatMessageFeedback]:
        """Bulk fetch used by `list_messages` to avoid N+1 queries when the
        chat UI hydrates a conversation."""
        if not message_ids:
            return {}
        result = await self.db.execute(
            select(ChatMessageFeedback).where(
                and_(
                    ChatMessageFeedback.user_id == user_id,
                    ChatMessageFeedback.message_id.in_(message_ids),
                )
            )
        )
        return {row.message_id: row for row in result.scalars().all()}

    async def get_feedback_rollup(
        self,
        *,
        agent_name: str | None = None,
        since: datetime | None = None,
        sample_limit: int = 10,
        include_deleted: bool = False,
    ) -> dict[str, object]:
        """Weekly rollup for the admin dashboard.

        Returns:
            `{up_count, down_count, top_reasons: [{reason, count}],
              sample_comments: [str, ...]}`

        `reasons` is a JSON list column; Postgres / SQLite don't share a
        cheap "unnest + group-by" shape, so we fetch the raw rows and
        aggregate in Python. Row volume here is bounded by the admin
        window (typically a week per agent) — trivial compared to the
        cost of an admin page render.

        P1-1: feedback on messages that have been soft-deleted (e.g. the
        student edited the turn and the assistant reply was truncated) is
        excluded by default — admins almost never want those in the rollup.
        """
        stmt = select(ChatMessageFeedback).join(
            ChatMessage, ChatMessageFeedback.message_id == ChatMessage.id
        )
        if agent_name:
            stmt = stmt.where(ChatMessage.agent_name == agent_name)
        if since is not None:
            stmt = stmt.where(ChatMessageFeedback.created_at >= since)
        if not include_deleted:
            stmt = stmt.where(ChatMessage.deleted_at.is_(None))

        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())

        up_count = sum(1 for r in rows if r.rating == "up")
        down_count = sum(1 for r in rows if r.rating == "down")

        reason_counts: dict[str, int] = {}
        for row in rows:
            if row.rating != "down":
                continue
            for reason in row.reasons or []:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        top_reasons = [
            {"reason": k, "count": v}
            for k, v in sorted(
                reason_counts.items(), key=lambda kv: kv[1], reverse=True
            )
        ]

        sample_stmt = (
            select(ChatMessageFeedback.comment)
            .where(ChatMessageFeedback.comment.is_not(None))
            .order_by(desc(ChatMessageFeedback.created_at))
            .limit(sample_limit)
        )
        needs_message_join = agent_name or since is not None or not include_deleted
        if needs_message_join:
            sample_stmt = sample_stmt.join(
                ChatMessage, ChatMessageFeedback.message_id == ChatMessage.id
            )
            if agent_name:
                sample_stmt = sample_stmt.where(ChatMessage.agent_name == agent_name)
            if since is not None:
                sample_stmt = sample_stmt.where(
                    ChatMessageFeedback.created_at >= since
                )
            if not include_deleted:
                sample_stmt = sample_stmt.where(ChatMessage.deleted_at.is_(None))
        sample_result = await self.db.execute(sample_stmt)
        sample_comments = [c for c in sample_result.scalars().all() if c]

        return {
            "up_count": up_count,
            "down_count": down_count,
            "top_reasons": top_reasons,
            "sample_comments": sample_comments,
        }
