"""Chat service — business logic on top of ChatRepository.

Owns:
  - title derivation (first user message truncated to ~60 chars)
  - ownership enforcement (raises 404 HTTPException so leaked IDs don't
    reveal the existence of another user's conversation)
  - token-count estimation (len // 4 is the accepted cheap heuristic for v1)
  - markdown export formatting (P1-9): pure function that turns a
    conversation + its messages into a student-ready transcript

Caller controls the transaction boundary. Routes rely on FastAPI's
`get_db` dependency to commit on success / rollback on exception.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_feedback import ChatMessageFeedback
from app.models.chat_message import ChatMessage
from app.models.conversation import Conversation
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import ChatFeedbackCreate, ChatMessageEditRequest

log = structlog.get_logger()


_TITLE_MAX_CHARS = 60


def derive_title(message: str) -> str:
    """Collapse whitespace and truncate to ~60 chars for sidebar display."""
    cleaned = " ".join(message.split())
    if not cleaned:
        return "New conversation"
    if len(cleaned) <= _TITLE_MAX_CHARS:
        return cleaned
    return cleaned[: _TITLE_MAX_CHARS - 1].rstrip() + "\u2026"


def estimate_tokens(text: str) -> int:
    """Rough token-count approximation. `len // 4` is the conventional
    heuristic for English text — good enough for UI stats until we wire a
    real tokenizer."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _format_ts(ts: datetime | None) -> str:
    """Human-readable `YYYY-MM-DD HH:MM` (UTC) for the body of the export."""
    if ts is None:
        return "unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def format_conversation_markdown(
    conversation: Conversation,
    messages: Iterable[ChatMessage],
    *,
    now: datetime | None = None,
) -> str:
    """Render a conversation + its messages as a clean Markdown transcript.

    Pure function — no DB access, no HTTPException. Keeps the logic testable
    without spinning up the ASGI stack. `now` is injectable so tests can pin
    the "Exported:" timestamp deterministically.
    """
    msgs = list(messages)
    title = (conversation.title or "Untitled conversation").strip() or "Untitled conversation"
    exported_at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)

    # Collect the set of distinct agent names that actually spoke; if there's
    # exactly one, use it in the header, else fall back to "Mixed" / "—".
    agent_names = {m.agent_name for m in msgs if m.role == "assistant" and m.agent_name}
    if len(agent_names) == 1:
        header_agent = next(iter(agent_names))
    elif len(agent_names) > 1:
        header_agent = "Mixed"
    else:
        header_agent = conversation.agent_name or "—"

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Exported: {exported_at.isoformat()}")
    lines.append(f"Agent: {header_agent}")
    lines.append(f"Messages: {len(msgs)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in msgs:
        ts_str = _format_ts(msg.created_at)
        if msg.role == "user":
            lines.append(f"## You · {ts_str}")
        elif msg.role == "assistant":
            if msg.agent_name:
                lines.append(f"## Tutor ({msg.agent_name}) · {ts_str}")
            else:
                lines.append(f"## Tutor · {ts_str}")
        else:
            # System / tool / future roles — keep them visible but clearly
            # labeled so students aren't confused about who said what.
            label = msg.role.capitalize() if msg.role else "System"
            lines.append(f"## {label} · {ts_str}")
        lines.append("")
        # Pass content through verbatim — student-facing markdown inside the
        # assistant reply (including `##` headings) is fine in an export; we
        # don't re-escape it.
        lines.append(msg.content if msg.content else "")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Trim the trailing blank-line + divider pair so the file doesn't end with
    # a dangling "---\n\n". Keep the final newline for POSIX-friendly files.
    while lines and lines[-1] == "":
        lines.pop()
    if lines and lines[-1] == "---":
        lines.pop()
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ChatRepository(db)

    # --- ownership helpers -----------------------------------------------

    async def _owned(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, *, with_messages: bool = False
    ) -> Conversation:
        conv = await self.repo.get_conversation(
            conversation_id, with_messages=with_messages
        )
        if conv is None or conv.user_id != user_id:
            # Deliberately 404 rather than 403 — leaking existence of another
            # user's conversation is a trivial but real information leak.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        return conv

    # --- conversation CRUD ------------------------------------------------

    async def create_conversation(
        self,
        *,
        user_id: uuid.UUID,
        agent_name: str | None = None,
        title: str | None = None,
    ) -> Conversation:
        conv = await self.repo.create_conversation(
            user_id=user_id, agent_name=agent_name, title=title
        )
        log.info(
            "chat.conversation_created",
            user_id=str(user_id),
            conversation_id=str(conv.id),
            agent_name=agent_name,
        )
        return conv

    async def get_conversation_with_messages(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, *, message_limit: int = 200
    ) -> tuple[Conversation, list[ChatMessage]]:
        conv = await self._owned(conversation_id, user_id)
        messages = await self.repo.list_messages(
            conversation_id, limit=message_limit, ascending=True
        )
        return conv, messages

    async def get_feedback_map_for_messages(
        self, messages: list[ChatMessage], user_id: uuid.UUID
    ) -> dict[uuid.UUID, ChatMessageFeedback]:
        """P1-5 — batch-fetch the current user's feedback on each message.

        Used by the route layer to inline `my_feedback` on `ChatMessageRead`
        responses, avoiding N+1 requests from the chat UI. Only assistant
        messages are queried (feedback on user/system rows is meaningless).
        """
        assistant_ids = [m.id for m in messages if m.role == "assistant"]
        return await self.repo.get_feedback_for_message_ids(
            assistant_ids, user_id
        )

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        include_archived: bool = False,
        search: str | None = None,
    ) -> list[tuple[Conversation, int]]:
        return await self.repo.list_conversations_for_user(
            user_id,
            include_archived=include_archived,
            search=search,
        )

    async def update(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        title: str | None = None,
        archived: bool | None = None,
        pinned: bool | None = None,
    ) -> Conversation:
        conv = await self._owned(conversation_id, user_id)
        updated = await self.repo.update_conversation(
            conv, title=title, archived=archived, pinned=pinned
        )
        log.info(
            "chat.conversation_updated",
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            title_changed=title is not None,
            archived_changed=archived is not None,
            pinned_changed=pinned is not None,
        )
        return updated

    async def delete(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
        # Ownership check first so another user's ID can't be probed via 204.
        await self._owned(conversation_id, user_id)
        await self.repo.delete_conversation(conversation_id)
        log.info(
            "chat.conversation_deleted",
            user_id=str(user_id),
            conversation_id=str(conversation_id),
        )

    # --- message persistence (called from stream endpoint) ----------------

    async def ensure_conversation_for_stream(
        self,
        *,
        conversation_id: uuid.UUID | None,
        user_id: uuid.UUID,
        agent_name: str,
        first_message: str,
    ) -> Conversation:
        """Resolve-or-create path for the stream endpoint.

        If `conversation_id` is given, verifies ownership (raises 404 on
        mismatch). Otherwise creates a new conversation with a title derived
        from `first_message`.
        """
        if conversation_id is not None:
            return await self._owned(conversation_id, user_id)

        return await self.create_conversation(
            user_id=user_id,
            agent_name=agent_name,
            title=derive_title(first_message),
        )

    async def record_user_message(
        self,
        conversation: Conversation,
        content: str,
    ) -> ChatMessage:
        # Back-fill the title if the conversation was created empty (or via
        # POST /conversations with no title). Keeps the sidebar useful even
        # when the first turn came through the stream endpoint.
        if not conversation.title:
            conversation.title = derive_title(content)
        return await self.repo.add_message(
            conversation_id=conversation.id,
            role="user",
            content=content,
            token_count=estimate_tokens(content),
        )

    async def record_assistant_message(
        self,
        conversation_id: uuid.UUID,
        content: str,
        *,
        agent_name: str | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> ChatMessage:
        """Persist a completed assistant turn.

        P1-2: `parent_id` points at the user message this reply is a
        response to. Setting it on every assistant turn makes the future
        regenerate flow trivial (siblings = assistant rows sharing a parent).
        Legacy calls without parent_id continue to work — siblings are
        skipped for those rows.
        """
        return await self.repo.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            agent_name=agent_name,
            token_count=estimate_tokens(content),
            parent_id=parent_id,
        )

    async def list_messages_page(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        before: uuid.UUID | None = None,
    ) -> list[ChatMessage]:
        await self._owned(conversation_id, user_id)
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        return await self.repo.list_messages(
            conversation_id, limit=limit, before=before, ascending=True
        )

    async def touch(self, conversation: Conversation) -> None:
        await self.repo.touch_conversation(conversation)

    # --- edit (P1-1) ------------------------------------------------------

    async def prepare_regenerate(
        self,
        *,
        assistant_message_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> tuple[ChatMessage, ChatMessage, list[ChatMessage]]:
        """P1-2 — validate + gather everything the regenerate stream needs.

        Returns `(assistant_message, parent_user_message, history)` where:
          - `assistant_message` is the source reply the caller wants a
            new variant of (ownership enforced, 404 on mismatch).
          - `parent_user_message` is the user turn that prompted it. We
            fall back to the most recent user message preceding the
            assistant by timestamp if `parent_id` is missing (e.g. legacy
            rows persisted before P1-2 started wiring it).
          - `history` is every non-deleted message in the conversation
            whose `created_at` is <= the parent user message, in
            chronological order. Assistant sibling variants on earlier
            parents stay in — the caller de-dups to canonical before
            feeding the LLM.

        Raises 400 if the target isn't an assistant message or 404 if we
        can't locate a user message to re-run against.
        """
        assistant_msg = await self._message_owned_by(assistant_message_id, user_id)
        if assistant_msg.role != "assistant":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only assistant messages can be regenerated.",
            )

        parent_msg: ChatMessage | None = None
        if assistant_msg.parent_id is not None:
            parent_msg = await self.repo.get_message(assistant_msg.parent_id)
            if parent_msg is not None and parent_msg.role != "user":
                parent_msg = None
        if parent_msg is None:
            # Legacy fallback: walk the transcript backwards from the
            # assistant row and pick the most recent user message.
            prior = await self.repo.get_messages_for_regenerate(
                assistant_msg.conversation_id, assistant_msg.id
            )
            for candidate in reversed(prior):
                if candidate.role == "user":
                    parent_msg = candidate
                    break
        if parent_msg is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No user message found to regenerate from.",
            )

        history = await self.repo.get_messages_for_regenerate(
            assistant_msg.conversation_id, parent_msg.id
        )
        return assistant_msg, parent_msg, history

    async def list_siblings(
        self, parent_message_id: uuid.UUID
    ) -> list[ChatMessage]:
        """P1-2 — proxy through to the repo for route-layer callers that
        need the sibling set after a regenerate stream completes."""
        return await self.repo.list_siblings(parent_message_id)

    async def get_message_for_user(
        self,
        *,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ChatMessage:
        """P1-2 — ownership-enforced single-message fetch for the sibling
        navigator. Delegates to `_message_owned_by` so missing / foreign /
        soft-deleted rows all produce the same 404."""
        return await self._message_owned_by(message_id, user_id)

    async def edit_user_message(
        self,
        *,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: ChatMessageEditRequest,
    ) -> ChatMessage:
        """Rewrite a user turn mid-conversation without losing the audit trail.

        Flow:
          1) Verify ownership (404 on mismatch / missing / foreign).
          2) Reject non-user messages with 400 — editing an assistant reply
             is the P1-2 "regenerate" flow, not this endpoint.
          3) Soft-delete every message in the same conversation whose
             `created_at >= target.created_at` (including the target row
             itself — we preserve it via `deleted_at`, not by mutating
             `content`, so the original text stays auditable).
          4) Insert a new user row with the edited content so the client can
             resume streaming from it.

        The frontend is expected to (a) clear its trailing messages to match
        the server state, then (b) call the stream endpoint with the returned
        id's content + the same conversation_id so the backend appends the
        new assistant turn.
        """
        msg = await self._message_owned_by(message_id, user_id)
        if msg.role != "user":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only user messages can be edited; use regenerate for assistant replies.",
            )

        # Step 3 — soft-delete the target + every downstream row.
        deleted_count = await self.repo.soft_delete_messages_from(
            msg.conversation_id, from_created_at=msg.created_at
        )

        # Step 4 — append a fresh user message with the edited content.
        # `parent_id` points at the original so the (future P1-3) branch
        # traversal can walk back to the source of the edit.
        new_msg = await self.repo.add_message(
            conversation_id=msg.conversation_id,
            role="user",
            content=payload.content,
            token_count=estimate_tokens(payload.content),
            parent_id=msg.id,
        )

        # Bump conversation.updated_at so the sidebar reorders correctly.
        conv = await self.repo.get_conversation(msg.conversation_id)
        if conv is not None:
            await self.repo.touch_conversation(conv)

        log.info(
            "chat.message_edited",
            user_id=str(user_id),
            conversation_id=str(msg.conversation_id),
            original_message_id=str(msg.id),
            new_message_id=str(new_msg.id),
            soft_deleted_count=deleted_count,
        )
        return new_msg

    # --- feedback (P1-5) --------------------------------------------------

    async def _message_owned_by(
        self, message_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatMessage:
        """Fetch a message and verify its conversation belongs to the caller.

        Raises 404 for a missing message or a message whose parent
        conversation belongs to another user — we deliberately don't
        distinguish the two so ID probing can't reveal existence.

        Soft-deleted messages are treated as missing (also 404) so the UI
        can't edit/rate a row the user has already truncated away.
        """
        msg = await self.repo.get_message(message_id)
        if msg is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            )
        # Ownership via the conversation. `_owned` raises 404 on mismatch.
        await self._owned(msg.conversation_id, user_id)
        return msg

    async def submit_feedback(
        self,
        *,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: ChatFeedbackCreate,
    ) -> ChatMessageFeedback:
        await self._message_owned_by(message_id, user_id)
        row = await self.repo.upsert_feedback(
            message_id=message_id,
            user_id=user_id,
            rating=payload.rating,
            reasons=payload.reasons,
            comment=payload.comment,
        )
        log.info(
            "chat.feedback_submitted",
            user_id=str(user_id),
            message_id=str(message_id),
            rating=payload.rating,
            reason_count=len(payload.reasons or []),
            has_comment=bool(payload.comment),
        )
        return row

    async def get_feedback(
        self, *, message_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatMessageFeedback | None:
        await self._message_owned_by(message_id, user_id)
        return await self.repo.get_feedback_for_user(message_id, user_id)

    async def feedback_rollup(
        self,
        *,
        agent_name: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, object]:
        return await self.repo.get_feedback_rollup(
            agent_name=agent_name, since=since
        )

    # --- export (P1-9) ----------------------------------------------------

    async def export_markdown(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> tuple[Conversation, str]:
        """Fetch + render a full markdown transcript.

        Returns `(conversation, markdown_body)` so the route can read the
        conversation's short-id / updated_at for the Content-Disposition
        filename without re-fetching. Enforces ownership via `_owned`.
        """
        conv = await self._owned(conversation_id, user_id)
        # No artificial cap — list_messages ascending is already bounded by
        # the 200-message limit at the service layer via list_messages_page,
        # but export should include every stored turn. The existing repo
        # method returns everything when `limit` is large.
        messages = await self.repo.list_messages(
            conversation_id, limit=10_000, ascending=True
        )
        body = format_conversation_markdown(conv, messages)
        log.info(
            "chat.conversation_exported",
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            message_count=len(messages),
        )
        return conv, body
