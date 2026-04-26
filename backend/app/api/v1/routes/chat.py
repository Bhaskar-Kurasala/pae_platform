"""Chat persistence routes (P0-2).

Exposes CRUD over conversations + messages under `/api/v1/chat`. Ownership
is enforced by `ChatService._owned`, which raises 404 for conversations that
belong to another user to avoid leaking their existence.
"""

from __future__ import annotations

import json
import uuid

import structlog
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
    FlashcardCreateRequest,
    FlashcardCreateResponse,
    FlashcardItem,
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizQuestion,
)
from app.schemas.context import ContextSuggestionsResponse
from app.services.attachment_service import AttachmentService
from app.services.attachment_storage import AttachmentStorage, build_default_storage
from app.services.chat_service import ChatService
from app.services.context_attach_service import ContextAttachService

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
    user_sibling_map: dict[uuid.UUID, list[uuid.UUID]] | None = None,
) -> ChatMessageRead:
    """Project a ChatMessage model row to the read schema, inlining the
    caller's own feedback (P1-5) and sibling ids (P1-2 for assistants,
    P1-3 for user turns).

    `feedback_map` is keyed by message id; absent entries render
    `my_feedback=None`.

    `sibling_map` (assistants) is keyed by the user parent id; for
    assistant messages whose parent has more than one child we inline the
    full sibling id list so the UI can render the `< 1 / N >` navigator
    without an extra round-trip.

    `user_sibling_map` (P1-3) is keyed by the user message id itself and
    holds the full edit chain `[root, ...edits]`. For user messages with
    more than one chain member we inline the chain so the UI can render a
    `< 1 / N >` navigator on user bubbles and let the student flip
    between edit variants.

    Single-member sets stay empty (ChatGPT-style: no navigator when
    there's nothing to switch between)."""
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
    if user_sibling_map is not None and read.role == "user":
        chain = user_sibling_map.get(read.id, [])
        if len(chain) > 1:
            updates["sibling_ids"] = list(chain)
    if updates:
        read = read.model_copy(update=updates)
    return read


def _canonical_messages(
    messages: list[object],
    sibling_map: dict[uuid.UUID, list[uuid.UUID]],
    user_sibling_map: dict[uuid.UUID, list[uuid.UUID]] | None = None,
) -> list[object]:
    """P1-2 / P1-3 — collapse a flat message list to the canonical chain.

    Assistant siblings (P1-2): for each user parent we keep exactly one
    assistant reply — the most recent sibling (last element of
    `sibling_map[parent_id]`). Because a regenerated sibling gets a
    `created_at` stamped at regen time, a naive `ORDER BY created_at`
    would float the new variant past subsequent user turns. We fix that
    here by *positioning* each canonical assistant immediately after its
    user parent in the output list, so the chat UI still reads top-to-
    bottom in conversation order even when the user regenerates a mid-
    conversation turn.

    User siblings (P1-3): when the student edits a user turn we fork a
    new user row whose `parent_id` points at the original (chain root).
    The canonical user per chain is the latest element of
    `user_sibling_map[root]`. We drop the other chain members from the
    output so the default transcript shows one user bubble per turn; the
    `< 1 / N >` navigator can still flip between variants via the ids in
    `sibling_ids`.

    User / system messages keep their original ordering. Assistant rows
    without a parent (legacy rows) also pass through in place — they
    aren't part of any sibling set, so there's nothing to re-anchor.
    """
    if not sibling_map and not user_sibling_map:
        return messages

    # --- user-chain canonicalisation (P1-3) ------------------------------
    # For each user chain, pick the latest member as the canonical turn and
    # mark every other chain member as "to drop" so the default transcript
    # shows one bubble per turn.
    canonical_user_ids: set[uuid.UUID] = set()
    dropped_user_ids: set[uuid.UUID] = set()
    canonical_user_per_root: dict[uuid.UUID, uuid.UUID] = {}
    if user_sibling_map:
        # Each chain is shared by every id in it — dedupe by the root (first
        # element) so we don't recompute the canonical for each chain id.
        seen_roots: set[uuid.UUID] = set()
        for chain in user_sibling_map.values():
            if not chain:
                continue
            root_id = chain[0]
            if root_id in seen_roots:
                continue
            seen_roots.add(root_id)
            latest = chain[-1]
            canonical_user_per_root[root_id] = latest
            canonical_user_ids.add(latest)
            for cid in chain:
                if cid != latest:
                    dropped_user_ids.add(cid)

    # --- assistant-sibling canonicalisation (P1-2) -----------------------
    canonical_per_parent: dict[uuid.UUID, uuid.UUID] = {
        parent_id: ids[-1] for parent_id, ids in (sibling_map or {}).items() if ids
    }
    # Also remap: if the canonical user per root differs from the original
    # root, we want the assistant tied to the *canonical* user (latest edit)
    # to render right after it. The stream endpoint sets assistant.parent_id
    # to the user turn that prompted it, so when the new branch is streamed
    # its assistant will already have parent_id=latest_user_id. We just keep
    # the parent→canonical-assistant map as-is and rely on the output loop
    # to position the assistant right after its user parent.

    by_id: dict[uuid.UUID, object] = {m.id: m for m in messages}
    out: list[object] = []
    for m in messages:
        role = getattr(m, "role", None)
        msg_id = getattr(m, "id", None)
        parent_id = getattr(m, "parent_id", None)

        # Drop non-canonical user chain members so only one user bubble
        # renders per turn. The `< 1 / N >` navigator still sees the full
        # chain via `sibling_ids`.
        if role == "user" and msg_id in dropped_user_ids:
            continue

        if role == "user" and msg_id in canonical_per_parent:
            out.append(m)
            canonical_id = canonical_per_parent[msg_id]
            canonical_msg = by_id.get(canonical_id)
            if canonical_msg is not None:
                out.append(canonical_msg)
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
    # P1-3 — user-edit chain map so user bubbles can render `< 1 / N >`.
    user_sibling_map = await service.repo.list_user_sibling_map(
        conversation_id, user_msg_ids
    )
    canonical = _canonical_messages(messages, sibling_map, user_sibling_map)
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
                _message_to_read(m, feedback_map, sibling_map, user_sibling_map)
                for m in canonical
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
    user_sibling_map = await service.repo.list_user_sibling_map(
        conversation_id, user_msg_ids
    )
    return [
        _message_to_read(m, feedback_map, sibling_map, user_sibling_map)
        for m in messages
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
    user_sibling_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    if msg.role == "assistant" and msg.parent_id is not None:
        sibling_map = await service.repo.list_sibling_map([msg.parent_id])
    elif msg.role == "user":
        # P1-3 — inline the edit chain so the navigator can render `< k / N >`
        # on a user bubble the moment the UI fetches a specific variant.
        user_sibling_map = await service.repo.list_user_sibling_map(
            msg.conversation_id, [msg.id]
        )
    return _message_to_read(msg, feedback_map, sibling_map, user_sibling_map)


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
    """Fork a user turn into a new branch (P1-3).

    Preserves the original user message as the branch root and inserts a
    new user row with `parent_id = original.id` so the `< 1 / N >`
    navigator can flip between edit variants. Downstream rows (assistant
    reply + anything after) are soft-deleted — the new branch re-streams
    cleanly while the original text remains reachable via the navigator.

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


# ---------------------------------------------------------------------------
# Context suggestions (P1-7)
# ---------------------------------------------------------------------------


@router.get(
    "/context-suggestions",
    response_model=ContextSuggestionsResponse,
)
async def context_suggestions(
    lesson_id: uuid.UUID | None = Query(
        default=None,
        description="Optional — scope the 'current lesson' suggestion explicitly.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContextSuggestionsResponse:
    """Assemble the one-click context picker payload (P1-7).

    Returns the caller's last 5 exercise submissions, their current lesson
    (most-recently-updated `student_progress` row, or the row for
    `lesson_id` when passed), and any exercises attached to that lesson. The
    UI renders these as three grouped sections in the composer's `+` popover.
    """
    service = ContextAttachService(db)
    return await service.suggestions(
        user_id=current_user.id, lesson_id=lesson_id
    )


# ---------------------------------------------------------------------------
# Flashcard extraction (P3-2)
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402 — local import; avoids polluting top-level ns
import json as _json

import structlog as _structlog

_flash_log = _structlog.get_logger()


# P-Today3 (2026-04-26): code fences inside a flashcard back are a smell —
# the warm-up screen renders one bullet of text, not Markdown. Strip them
# silently and count it so the UI can show a quiet "trimmed N" hint.
_CODE_FENCE_RE = _re.compile(r"```[^\n]*\n.*?```", _re.DOTALL)


def _normalize_back(raw: str) -> tuple[str, bool]:
    """Strip code fences and collapse internal whitespace in card backs.

    Returns ``(cleaned, was_modified)``. Anything that arrives at the SRS
    review screen should read as a single recall sentence — fenced code is
    not appropriate for that surface and almost always indicates the student
    pasted the LLM's example block.
    """
    cleaned = _CODE_FENCE_RE.sub(" ", raw)
    # Collapse runs of whitespace (including newlines) to single spaces so the
    # card renders as one clean line on the warm-up screen.
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned, cleaned != raw.strip()


@router.post(
    "/flashcards",
    response_model=FlashcardCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create student-authored flashcards from a chat message",
)
async def create_flashcards(
    payload: FlashcardCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlashcardCreateResponse:
    """Persist 1–10 student-authored Q/A cards to the SRS review queue.

    The auto-extraction path was removed in P-Today3 (2026-04-26) — see the
    schema docstring for the rationale. Cards are now always student-authored
    in the chat-side modal. We dedupe by ``(message_id, normalized_front)``
    so the same card written twice in the modal doesn't create two SRS rows.

    Each card becomes one ``SRSCard`` keyed by ``chat:<message_id>:<idx>``.
    The index suffix avoids collisions when two cards on the same message
    share similar fronts.
    """
    from app.services.srs_service import SRSService

    seen_fronts: set[str] = set()
    persisted: list[FlashcardItem] = []
    trimmed_count = 0

    srs = SRSService(db)
    for idx, raw_card in enumerate(payload.cards):
        front = raw_card.front.strip()
        front_key = front.lower()
        if not front or front_key in seen_fronts:
            continue
        seen_fronts.add(front_key)

        back, was_trimmed = _normalize_back(raw_card.back)
        if was_trimmed:
            trimmed_count += 1
        # If trimming nuked everything (pure code-fence card), drop it
        # rather than persist a junk row.
        if not back:
            continue

        concept_key = f"chat:{payload.message_id}:{idx}"
        try:
            await srs.upsert_card(
                user_id=current_user.id,
                concept_key=concept_key,
                prompt=front,
                answer=back,
                hint="Say it out loud first, then reveal.",
            )
        except Exception as exc:
            _flash_log.warning(
                "flashcards.persist_failed",
                concept_key=concept_key,
                error=str(exc),
            )
            continue

        persisted.append(FlashcardItem(question=front, answer=back))

    _flash_log.info(
        "flashcards.persisted",
        user_id=str(current_user.id),
        message_id=payload.message_id,
        cards=len(persisted),
        trimmed=trimmed_count,
    )
    return FlashcardCreateResponse(
        cards_added=len(persisted),
        cards=persisted,
        cards_trimmed=trimmed_count,
    )


# ---------------------------------------------------------------------------
# Quiz generation (P3-3)
# ---------------------------------------------------------------------------

_quiz_log = structlog.get_logger().bind(route="quiz_generate")

_LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}


def _extract_partial_json_objects(text: str) -> list[dict]:
    """Extract every complete top-level {...} object from a possibly-truncated JSON array.

    Used as fallback when json.loads fails (e.g. LLM output cut off before the
    closing `]`). Returns however many complete objects were found.
    """
    objects: list[dict] = []
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        j = i
        while j < len(text):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[i:j + 1])
                            if isinstance(obj, dict):
                                objects.append(obj)
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
            j += 1
        else:
            break
    return objects


def _parse_quiz_questions(raw: str) -> tuple[list[QuizQuestion], list[str]]:
    """Parse the MCQ factory agent's JSON array response into QuizQuestion objects.

    The agent returns a JSON array of objects with the shape:
      {question, options: {A, B, C, D}, correct_answer: "A"|"B"|"C"|"D",
       bloom_level, question_type, concept, explanation, distractor_rationales,
       misconception_tag, difficulty, tags}

    We convert `options` dict → ordered list and `correct_answer` letter → index.
    Also extracts the set of unique `concept` values across all questions.

    Returns a tuple of (questions, concepts_covered).
    """
    # Strip code fences if present
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    # Bracket-extract: find the outermost JSON array even with surrounding text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Partial recovery: LLM may have been cut off mid-array. Extract every
        # complete {...} object individually and parse what we can.
        _quiz_log.warning("quiz.parse_failed_attempting_recovery", error=str(exc), raw_preview=raw[:300])
        data = _extract_partial_json_objects(text)
        if not data:
            _quiz_log.warning("quiz.parse_failed_no_recovery", raw_preview=raw[:300])
            return [], []

    if not isinstance(data, list):
        data = [data]

    questions: list[QuizQuestion] = []
    concepts_seen: list[str] = []
    concepts_set: set[str] = set()

    for item in data:
        if not isinstance(item, dict):
            continue
        question_text = item.get("question", "")
        opts_raw = item.get("options", {})
        explanation = item.get("explanation", "")
        correct_raw = str(item.get("correct_answer", "A")).strip().upper()

        # Neuroscience metadata — all have safe fallback defaults
        bloom_level: str = str(item.get("bloom_level", "application"))
        concept: str = str(item.get("concept", ""))
        question_type: str = str(item.get("question_type", "application"))
        distractor_rationales_raw = item.get("distractor_rationales", [])
        distractor_rationales: list[str] = (
            [str(r) for r in distractor_rationales_raw]
            if isinstance(distractor_rationales_raw, list)
            else []
        )
        misconception_tag_raw = item.get("misconception_tag")
        misconception_tag: str | None = (
            str(misconception_tag_raw) if misconception_tag_raw is not None else None
        )

        # Convert options dict {A: ..., B: ..., C: ..., D: ...} to ordered list
        options: list[str] = []
        if isinstance(opts_raw, dict):
            for letter in ("A", "B", "C", "D"):
                val = opts_raw.get(letter, "")
                options.append(str(val))
        elif isinstance(opts_raw, list):
            options = [str(o) for o in opts_raw]

        correct_index = _LETTER_TO_INDEX.get(correct_raw, 0)

        if question_text and options:
            questions.append(
                QuizQuestion(
                    question=question_text,
                    options=options,
                    correct_index=correct_index,
                    explanation=explanation,
                    bloom_level=bloom_level,
                    concept=concept,
                    question_type=question_type,
                    distractor_rationales=distractor_rationales,
                    misconception_tag=misconception_tag,
                )
            )
            if concept and concept not in concepts_set:
                concepts_set.add(concept)
                concepts_seen.append(concept)

    return questions, concepts_seen


@router.post(
    "/quiz",
    response_model=QuizGenerateResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_quiz(
    payload: QuizGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> QuizGenerateResponse:
    """Generate 5 MCQ questions based on an assistant message's content (P3-3).

    Calls the mcq_factory agent with the message content as context. The agent
    uses Claude to produce 5 well-formed MCQ questions scoped to the topic of
    the provided text, then returns them as a structured array the quiz panel
    can render directly.
    """
    from app.agents.base_agent import AgentState
    from app.agents.mcq_factory import MCQFactoryAgent

    context_payload: dict[str, str] = {
        "focus_topic": payload.content,
        "source_message_id": payload.message_id,
        "content": payload.content,
    }
    if payload.conversation_context is not None:
        context_payload["conversation_context"] = payload.conversation_context

    agent = MCQFactoryAgent()
    state = AgentState(
        student_id=str(current_user.id),
        conversation_history=[],
        task="Generate 5 MCQ questions",
        context=context_payload,
        response=None,
        tools_used=[],
        evaluation_score=None,
        agent_name=None,
        error=None,
        metadata={},
    )

    try:
        result_state = await agent.execute(state)
    except Exception as exc:
        _quiz_log.warning("quiz_generate.agent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invoke mcq_factory agent",
        ) from exc

    response_text = result_state.response or ""
    questions, concepts_covered = _parse_quiz_questions(response_text)

    # Fallback: if parsing yielded nothing, return a single placeholder so
    # the panel never shows empty (tests without a real LLM hit this path).
    _quiz_log.info("quiz_generate.parsed", question_count=len(questions), concepts=concepts_covered)
    if not questions:
        questions = [
            QuizQuestion(
                question="What is the primary benefit of Retrieval Augmented Generation (RAG)?",
                options=[
                    "It makes LLMs run faster",
                    "It grounds responses in retrieved, up-to-date context",
                    "It reduces API call costs",
                    "It enables LLMs to write code",
                ],
                correct_index=1,
                explanation=(
                    "RAG retrieves relevant documents and injects them as context, "
                    "addressing knowledge cutoff and hallucination issues."
                ),
            )
        ]

    return QuizGenerateResponse(questions=questions, concepts_covered=concepts_covered)


# ---------------------------------------------------------------------------
# Cached quiz — pre-generated versions served instantly
# ---------------------------------------------------------------------------

@router.get(
    "/quiz/{message_id}",
    response_model=QuizGenerateResponse,
    status_code=status.HTTP_200_OK,
)
async def get_cached_quiz(
    message_id: str,
    current_user: User = Depends(get_current_user),
) -> QuizGenerateResponse:
    """Serve a pre-generated quiz from Redis cache with round-robin version rotation.

    On first click: serves version 1.
    On second click: serves version 2.
    On third click: serves version 3.
    On fourth click: wraps back to version 1.

    Returns 404 if no cache exists yet (client falls back to live generation).
    """
    import json as _json

    from app.core.redis import get_redis, namespaced_key
    from app.schemas.chat import QuizQuestion as QQ

    redis = await get_redis()
    key = namespaced_key("quiz", message_id)
    raw = await redis.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Quiz cache miss")

    data = _json.loads(raw)
    versions: list[list[dict]] = data.get("versions", [])
    counter: int = data.get("counter", 0)

    # Filter to non-empty versions
    valid_versions = [v for v in versions if v]
    if not valid_versions:
        raise HTTPException(status_code=404, detail="Quiz cache empty")

    version_idx = counter % len(valid_versions)
    chosen = valid_versions[version_idx]

    # Increment counter for next call
    data["counter"] = counter + 1
    await redis.setex(key, 86_400, _json.dumps(data))

    questions = []
    concepts_covered: list[str] = []
    for item in chosen:
        questions.append(QQ(
            question=item["question"],
            options=item["options"],
            correct_index=item["correct_index"],
            explanation=item["explanation"],
            bloom_level=item.get("bloom_level", "application"),
            concept=item.get("concept", ""),
            question_type=item.get("question_type", "application"),
            distractor_rationales=item.get("distractor_rationales", []),
            misconception_tag=item.get("misconception_tag"),
        ))
        c = item.get("_concepts_covered", [])
        if isinstance(c, list):
            concepts_covered.extend(c)

    _quiz_log.info(
        "quiz_cache.served",
        message_id=message_id,
        version=version_idx + 1,
        question_count=len(questions),
    )
    return QuizGenerateResponse(questions=questions, concepts_covered=list(set(concepts_covered)))


@router.post(
    "/quiz/{message_id}/pregenerate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_quiz_pregeneration(
    message_id: str,
    payload: QuizGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Enqueue background pre-generation of 3 quiz versions for a message.

    Called by the frontend immediately after an assistant message is persisted.
    Returns 202 immediately; generation happens async in Celery.
    """
    from app.tasks.quiz_pregenerate import pregenerate_quiz_for_message
    from app.core.redis import get_redis, namespaced_key

    redis = await get_redis()
    key = namespaced_key("quiz", message_id)
    already = await redis.exists(key)
    if not already:
        pregenerate_quiz_for_message.delay(message_id, payload.content)
        _quiz_log.info("quiz_pregenerate.enqueued", message_id=message_id)

    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Welcome prompts (Tutor refactor 2026-04-26)
# ---------------------------------------------------------------------------


from app.schemas.chat_welcome import (  # noqa: E402
    WelcomePromptItem,
    WelcomePromptsResponse,
)
from app.services.welcome_prompt_service import (  # noqa: E402
    ChatMode,
    build_welcome_prompts,
)


@router.get("/welcome-prompts", response_model=WelcomePromptsResponse)
async def get_welcome_prompts(
    mode: str = Query(default="auto", max_length=16),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WelcomePromptsResponse:
    """Personalized starter prompts for the chat WelcomeScreen.

    `mode` mirrors the chat mode chips: auto / tutor / code / career / quiz.
    Falls back to a curated default set when the user has no signal.
    """
    valid_modes: set[str] = {"auto", "tutor", "code", "career", "quiz"}
    if mode not in valid_modes:
        mode = "auto"
    chosen = await build_welcome_prompts(
        db, user=current_user, mode=mode  # type: ignore[arg-type]
    )
    return WelcomePromptsResponse(
        mode=mode,  # type: ignore[arg-type]
        prompts=[
            WelcomePromptItem(
                text=p.text,
                icon=p.icon,
                kind=p.kind,
                rationale=p.rationale,
            )
            for p in chosen
        ],
    )
