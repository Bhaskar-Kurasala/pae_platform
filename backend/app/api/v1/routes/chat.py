"""Chat persistence routes (P0-2).

Exposes CRUD over conversations + messages under `/api/v1/chat`. Ownership
is enforced by `ChatService._owned`, which raises 404 for conversations that
belong to another user to avoid leaking their existence.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.chat import (
    ChatAttachmentRead,
    ChatFeedbackCreate,
    ChatFeedbackRead,
    ChatMessageEditRequest,
    ChatMessageRead,
    ConversationCreate,
    ConversationListItem,
    ConversationRead,
    ConversationUpdate,
)
from app.services.attachment_service import AttachmentService
from app.services.attachment_storage import AttachmentStorage, build_default_storage
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


def _service(db: AsyncSession = Depends(get_db)) -> ChatService:
    return ChatService(db)


@router.post(
    "/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    conv = await service.create_conversation(
        user_id=current_user.id,
        agent_name=payload.agent_name,
        title=payload.title,
    )
    # Freshly-created conversations have no messages yet — return the empty
    # list rather than making the caller re-fetch.
    return ConversationRead.model_validate(
        {
            "id": conv.id,
            "user_id": conv.user_id,
            "agent_name": conv.agent_name,
            "title": conv.title,
            "archived_at": conv.archived_at,
            "pinned_at": conv.pinned_at,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": [],
        }
    )


@router.get("/conversations", response_model=list[ConversationListItem])
async def list_conversations(
    include_archived: bool = Query(default=False),
    q: str | None = Query(default=None, max_length=255),
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> list[ConversationListItem]:
    pairs = await service.list_for_user(
        current_user.id,
        include_archived=include_archived,
        search=q,
    )
    return [
        ConversationListItem(
            id=conv.id,
            title=conv.title,
            agent_name=conv.agent_name,
            updated_at=conv.updated_at,
            archived_at=conv.archived_at,
            pinned_at=conv.pinned_at,
            message_count=count,
        )
        for conv, count in pairs
    ]


def _message_to_read(
    msg: ChatMessageRead | object,
    feedback_map: dict[uuid.UUID, object],
    sibling_map: dict[uuid.UUID, list[uuid.UUID]] | None = None,
) -> ChatMessageRead:
    """Project a ChatMessage model row to the read schema, inlining the
    caller's own feedback (P1-5) and assistant sibling ids (P1-2).

    `feedback_map` is keyed by message id; absent entries render
    `my_feedback=None`. `sibling_map` is keyed by the user parent id; for
    assistant messages whose parent has more than one child we inline the
    full sibling id list so the UI can render the `< 1 / N >` navigator
    without an extra round-trip. Single-child sets stay empty (ChatGPT-
    style: no navigator when there's nothing to switch between)."""
    read = ChatMessageRead.model_validate(msg)
    updates: dict[str, object] = {}
    fb = feedback_map.get(read.id)  # type: ignore[arg-type]
    if fb is not None:
        updates["my_feedback"] = ChatFeedbackRead.model_validate(fb)
    if (
        sibling_map is not None
        and read.role == "assistant"
        and read.parent_id is not None
    ):
        siblings = sibling_map.get(read.parent_id, [])
        if len(siblings) > 1:
            updates["sibling_ids"] = list(siblings)
    if updates:
        read = read.model_copy(update=updates)
    return read


def _canonical_messages(
    messages: list[object],
    sibling_map: dict[uuid.UUID, list[uuid.UUID]],
) -> list[object]:
    """P1-2 — collapse a flat message list to the "canonical" chain.

    For each user parent we keep exactly one assistant reply — the most
    recent sibling (last element of `sibling_map[parent_id]`). Because a
    regenerated sibling gets a `created_at` stamped at regen time, a naive
    `ORDER BY created_at` would float the new variant past subsequent
    user turns. We fix that here by *positioning* each canonical
    assistant immediately after its user parent in the output list, so
    the chat UI still reads top-to-bottom in conversation order even
    when the user regenerates a mid-conversation turn.

    User / system messages keep their original ordering. Assistant rows
    without a parent (legacy rows) also pass through in place — they
    aren't part of any sibling set, so there's nothing to re-anchor.
    """
    if not sibling_map:
        return messages
    canonical_per_parent: dict[uuid.UUID, uuid.UUID] = {
        parent_id: ids[-1] for parent_id, ids in sibling_map.items() if ids
    }
    # Index every message by id so we can inline the canonical sibling at
    # the parent's position even if the DB row wasn't in the passed-in
    # slice (unlikely at the current 200-msg limit, but defensive).
    by_id: dict[uuid.UUID, object] = {m.id: m for m in messages}
    placed_canonical: set[uuid.UUID] = set()
    out: list[object] = []
    for m in messages:
        role = getattr(m, "role", None)
        msg_id = getattr(m, "id", None)
        parent_id = getattr(m, "parent_id", None)
        if role == "user" and msg_id in canonical_per_parent:
            out.append(m)
            canonical_id = canonical_per_parent[msg_id]
            canonical_msg = by_id.get(canonical_id)
            if canonical_msg is not None:
                out.append(canonical_msg)
                placed_canonical.add(canonical_id)
            continue
        if role == "assistant" and parent_id in canonical_per_parent:
            # Drop every assistant sibling here — the canonical one was
            # already inserted right after its user parent above.
            continue
        out.append(m)
    return out


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: uuid.UUID,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    conv, messages = await service.get_conversation_with_messages(
        conversation_id, current_user.id, message_limit=200
    )
    feedback_map = await service.get_feedback_map_for_messages(
        messages, current_user.id
    )
    user_msg_ids = [m.id for m in messages if m.role == "user"]
    sibling_map = await service.repo.list_sibling_map(user_msg_ids)
    canonical = _canonical_messages(messages, sibling_map)
    return ConversationRead.model_validate(
        {
            "id": conv.id,
            "user_id": conv.user_id,
            "agent_name": conv.agent_name,
            "title": conv.title,
            "archived_at": conv.archived_at,
            "pinned_at": conv.pinned_at,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": [
                _message_to_read(m, feedback_map, sibling_map) for m in canonical
            ],
        }
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageRead],
)
async def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    before: uuid.UUID | None = Query(default=None),
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> list[ChatMessageRead]:
    messages = await service.list_messages_page(
        conversation_id, current_user.id, limit=limit, before=before
    )
    feedback_map = await service.get_feedback_map_for_messages(
        messages, current_user.id
    )
    user_msg_ids = [m.id for m in messages if m.role == "user"]
    sibling_map = await service.repo.list_sibling_map(user_msg_ids)
    return [
        _message_to_read(m, feedback_map, sibling_map) for m in messages
    ]


@router.patch(
    "/conversations/{conversation_id}", response_model=ConversationRead
)
async def update_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    conv = await service.update(
        conversation_id,
        current_user.id,
        title=payload.title,
        archived=payload.archived,
        pinned=payload.pinned,
    )
    return ConversationRead.model_validate(
        {
            "id": conv.id,
            "user_id": conv.user_id,
            "agent_name": conv.agent_name,
            "title": conv.title,
            "archived_at": conv.archived_at,
            "pinned_at": conv.pinned_at,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": [],
        }
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> None:
    await service.delete(conversation_id, current_user.id)
    return None


# ---------------------------------------------------------------------------
# Single message fetch (P1-2 sibling navigation)
# ---------------------------------------------------------------------------


@router.get(
    "/messages/{message_id}",
    response_model=ChatMessageRead,
)
async def get_message(
    message_id: uuid.UUID,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> ChatMessageRead:
    """Fetch a single chat message by id.

    Used by the P1-2 sibling navigator: when the student clicks
    `< 1 / 3 >`, the UI resolves the selected sibling id via this endpoint
    so it can swap the bubble's content. Ownership is enforced — a foreign
    message returns 404 (we don't distinguish missing from forbidden).

    The projection inlines both the caller's own feedback and the sibling
    id list so the navigator can re-render `< k / N >` correctly when the
    user lands on a newly-fetched variant.
    """
    msg = await service.get_message_for_user(
        message_id=message_id, user_id=current_user.id
    )
    feedback_map = await service.get_feedback_map_for_messages(
        [msg], current_user.id
    )
    sibling_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    if msg.role == "assistant" and msg.parent_id is not None:
        sibling_map = await service.repo.list_sibling_map([msg.parent_id])
    return _message_to_read(msg, feedback_map, sibling_map)


# ---------------------------------------------------------------------------
# Edit user message (P1-1)
# ---------------------------------------------------------------------------


@router.post(
    "/messages/{message_id}/edit",
    response_model=ChatMessageRead,
    status_code=status.HTTP_200_OK,
)
async def edit_user_message(
    message_id: uuid.UUID,
    payload: ChatMessageEditRequest,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> ChatMessageRead:
    """Rewrite a user turn and truncate downstream history (P1-1).

    Soft-deletes every message in the same conversation with
    `created_at >= target.created_at` (preserving the audit trail) and
    inserts a new user message with `payload.content`. The frontend then
    fires a new stream request with `conversation_id` so the backend
    appends the new assistant reply.

    Returns the newly-inserted user row so the client can key it as the
    latest user turn in local state without re-fetching the conversation.
    """
    new_msg = await service.edit_user_message(
        message_id=message_id,
        user_id=current_user.id,
        payload=payload,
    )
    return ChatMessageRead.model_validate(new_msg)


# ---------------------------------------------------------------------------
# Feedback (P1-5)
# ---------------------------------------------------------------------------


@router.post(
    "/messages/{message_id}/feedback",
    response_model=ChatFeedbackRead,
    status_code=status.HTTP_200_OK,
)
async def submit_message_feedback(
    message_id: uuid.UUID,
    payload: ChatFeedbackCreate,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> ChatFeedbackRead:
    """Thumbs up/down a specific assistant message.

    Upsert semantics: a second POST from the same user on the same message
    replaces the existing row (enforced by the service + a DB unique
    constraint). Returns 404 if the message doesn't exist or its
    conversation isn't owned by the caller — we deliberately don't
    distinguish those cases, matching the conversation routes' style.
    """
    row = await service.submit_feedback(
        message_id=message_id,
        user_id=current_user.id,
        payload=payload,
    )
    return ChatFeedbackRead.model_validate(row)


@router.get(
    "/messages/{message_id}/feedback",
    response_model=ChatFeedbackRead | None,
)
async def get_message_feedback(
    message_id: uuid.UUID,
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> ChatFeedbackRead | None:
    """Return the caller's own feedback on a message, or `null` if none.

    Used by the chat UI to hydrate thumb state when a conversation loads
    via the lazy path; the batch-inline path on `GET /conversations/{id}`
    remains the default and avoids N+1 fetches.
    """
    row = await service.get_feedback(
        message_id=message_id, user_id=current_user.id
    )
    if row is None:
        return None
    return ChatFeedbackRead.model_validate(row)


@router.get(
    "/conversations/{conversation_id}/export",
    responses={
        200: {
            "content": {"text/markdown": {}},
            "description": "Markdown transcript of the conversation.",
        },
        400: {"description": "Unsupported export format."},
        404: {"description": "Conversation not found or not owned."},
    },
)
async def export_conversation(
    conversation_id: uuid.UUID,
    format: str = Query(default="md", description="Export format — only 'md' supported for now."),
    service: ChatService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Export a conversation as a plain Markdown transcript (P1-9).

    Returns `text/markdown; charset=utf-8` with a `Content-Disposition:
    attachment` header so the browser triggers a download. Ownership is
    enforced via the service layer (404 on mismatch).
    """
    if format != "md":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format: {format!r}. Only 'md' is supported.",
        )
    conv, body = await service.export_markdown(conversation_id, current_user.id)
    short_id = conv.id.hex[:8]
    # Use updated_at (falling back to created_at); format as YYYYMMDD for the
    # filename. Human-readable, stable across the day, short enough not to
    # blow past filesystem filename limits.
    when = conv.updated_at or conv.created_at
    date_str = when.strftime("%Y%m%d") if when else "00000000"
    filename = f"conversation-{short_id}-{date_str}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Expose the filename header so the browser fetch in the frontend
            # can parse it (default CORS exposes only simple headers).
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# ---------------------------------------------------------------------------
# Attachments (P1-6)
# ---------------------------------------------------------------------------


def _storage_dep() -> AttachmentStorage:
    """Route-level dependency so tests can override storage via
    `app.dependency_overrides[_storage_dep]`."""
    return build_default_storage()


def _attachment_service(
    db: AsyncSession = Depends(get_db),
    storage: AttachmentStorage = Depends(_storage_dep),
) -> AttachmentService:
    return AttachmentService(db, storage)


@router.post(
    "/attachments",
    response_model=ChatAttachmentRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"description": "File too large (>10 MB)."},
        415: {"description": "Unsupported attachment type."},
    },
)
async def upload_attachment(
    file: UploadFile = File(...),
    service: AttachmentService = Depends(_attachment_service),
    current_user: User = Depends(get_current_user),
) -> ChatAttachmentRead:
    """Upload a single attachment for a future chat turn.

    Returns a slim row (`id, filename, mime_type, size_bytes`) that the
    client can reference by id on the next `/api/v1/agents/stream` call via
    `attachment_ids`. The attachment is created with `message_id = NULL`
    until the stream endpoint binds it.
    """
    data = await file.read()
    declared_mime = file.content_type or ""
    filename = file.filename or "attachment.bin"
    row = await service.upload(
        user_id=current_user.id,
        filename=filename,
        mime_type=declared_mime,
        data=data,
    )
    return ChatAttachmentRead.model_validate(row)
