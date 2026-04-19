"""Pydantic schemas for the persisted chat surface (P0-2).

Covers the `/api/v1/chat/*` endpoints and the persistence payloads used by
the streaming endpoint. `role` is validated against the small closed set we
support today; if we add more roles later (e.g. 'tool'), extend
`ChatRole` rather than loosening the type.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChatRole = Literal["user", "assistant", "system"]

# P1-5 — closed set of valid ratings. Kept Literal (not Enum) to match the
# DB representation (a String column with a CHECK constraint) and the
# existing `ChatRole` style in this module.
ChatRating = Literal["up", "down"]


class ConversationCreate(BaseModel):
    agent_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=255)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    archived: bool | None = None
    # P1-8 — `pinned` is a tri-state from the wire: omitted (None) leaves the
    # state alone, True sets `pinned_at=now`, False clears it. Matches the
    # existing `archived` semantics so the sidebar ⋯ menu's Pin / Unpin
    # toggle only needs one endpoint.
    pinned: bool | None = None


class ChatMessageEditRequest(BaseModel):
    """P1-1 — body for POST /chat/messages/{id}/edit.

    `content` holds the replacement text for the user turn. We cap at 10k
    characters to match the composer's upper bound; anything longer is
    almost certainly a paste accident rather than a real question.
    """

    content: str = Field(min_length=1, max_length=10000)


class ChatFeedbackCreate(BaseModel):
    """P1-5 — body for POST /chat/messages/{id}/feedback.

    `reasons` is optional and validated only by length (we don't lock it to
    a Literal set so the frontend can add new chip categories without a
    backend release). `comment` is capped to a generous 2 KB — more than
    enough for a student-facing "why was this bad?" textarea.
    """

    rating: ChatRating
    reasons: list[str] | None = Field(default=None, max_length=10)
    comment: str | None = Field(default=None, max_length=2000)


class ChatFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID
    rating: ChatRating
    reasons: list[str] | None = None
    comment: str | None = None
    created_at: datetime


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: ChatRole
    content: str
    agent_name: str | None = None
    token_count: int | None = None
    parent_id: uuid.UUID | None = None
    created_at: datetime
    # P1-5 — the current user's own feedback on this message, if any. The
    # service layer joins `chat_message_feedback` for the logged-in user so
    # the chat UI can hydrate thumb state without an N+1 round trip. Remains
    # `None` when the caller hasn't rated the message (or for user/system
    # role rows — ratings only make sense on assistant turns).
    my_feedback: ChatFeedbackRead | None = None
    # P1-2 — assistant message variants that share a user parent (regenerate
    # siblings). Empty list when this is the only reply, otherwise contains
    # every sibling's id (including this message's own id) ordered by
    # created_at ascending so the UI can render a "<1 / N>" navigator and
    # key into the set by index.
    sibling_ids: list[uuid.UUID] = Field(default_factory=list)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    agent_name: str | None = None
    title: str | None = None
    archived_at: datetime | None = None
    # P1-8 — nullable pin timestamp. `None` = not pinned; a populated value
    # means the row stays at the top of the sidebar, ordered by pin time.
    pinned_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ConversationListItem(BaseModel):
    """Slim projection for the sidebar list — no message bodies."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None = None
    agent_name: str | None = None
    updated_at: datetime
    archived_at: datetime | None = None
    # P1-8 — sidebar pinned section renders rows with `pinned_at != None`
    # above the divider, ordered by `pinned_at DESC`.
    pinned_at: datetime | None = None
    message_count: int = 0


# P1-6 — attachments ---------------------------------------------------------


class ChatAttachmentRead(BaseModel):
    """Slim projection used by the upload endpoint response and the
    chat-api hydration path. Does NOT include the storage key — that's a
    backend-only implementation detail."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
