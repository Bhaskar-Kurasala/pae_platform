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


class ChatRegenerateRequest(BaseModel):
    """P2-4 — optional body for POST /chat/messages/{id}/regenerate.

    When the student clicks the routing-reason dropdown and picks a
    different agent, the UI POSTs ``{agent_override: "socratic_tutor"}``
    so the regenerate stream runs under that agent instead of re-using
    the original assistant's `agent_name`. The value is validated against
    ``ROUTABLE_AGENTS`` at the route layer; unknown names fall back to
    the default regenerate path (no 422 — we'd rather keep the stream
    alive than surface a hard error for a stale UI choice).
    """

    agent_override: str | None = Field(default=None, max_length=100)


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
    # P2-5 — hover-panel metadata persisted by the stream endpoint once the
    # reply completes. Rendered on the assistant bubble as e.g.
    # `model · 120ms first / 2.3s total · 450 in / 890 out tokens`. All
    # nullable so historical rows + stream-error paths stay valid.
    first_token_ms: int | None = None
    total_duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
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


# P3-2 — flashcard extraction ---------------------------------------------------


class FlashcardExtractRequest(BaseModel):
    """P3-2 — body for POST /chat/flashcards.

    `message_id` is stored as a plain string (not UUID) because the UI may
    pass client-generated ids for messages that haven't been persisted yet.
    `content` holds the assistant message text to extract cards from.
    """

    message_id: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=50000)


class FlashcardItem(BaseModel):
    question: str
    answer: str


class FlashcardExtractResponse(BaseModel):
    cards_added: int
    cards: list[FlashcardItem] = Field(default_factory=list)


# P3-3 — quiz generation -------------------------------------------------


class QuizGenerateRequest(BaseModel):
    """P3-3 — body for POST /chat/quiz.

    `message_id` is stored for audit/tracing; `content` is the assistant
    message text passed as `focus_topic` to the adaptive_quiz agent.
    `conversation_context` is the optional student question that prompted
    the assistant message — passed to the MCQ factory to anchor question
    scenarios to the student's actual learning gap.
    """

    message_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=20000)
    conversation_context: str | None = Field(
        default=None,
        max_length=5000,
        description="The student's question that prompted this answer (optional).",
    )


class QuizQuestion(BaseModel):
    """A single MCQ item returned by the quiz endpoint.

    Legacy fields (`question`, `options`, `correct_index`, `explanation`) are
    required and match the original schema.  All neuroscience-metadata fields
    are optional with safe defaults so existing parsers that omit them remain
    fully compatible.
    """

    question: str
    options: list[str]
    correct_index: int
    explanation: str

    # --- neuroscience metadata (all optional with safe defaults) ----------
    bloom_level: str = Field(
        default="application",
        description="Bloom's taxonomy level: recall | comprehension | application | analysis",
    )
    concept: str = Field(
        default="",
        description="The atomic concept this question tests (e.g. 'HNSW graph search').",
    )
    question_type: str = Field(
        default="application",
        description="MCQ type: foundation | application | analysis | misconception_trap",
    )
    distractor_rationales: list[str] = Field(
        default_factory=list,
        description="One sentence per wrong option explaining WHY it is tempting, in left-to-right order of wrong options.",
    )
    misconception_tag: str | None = Field(
        default=None,
        description="Slug identifying the misconception targeted (set only on misconception_trap questions).",
    )


class QuizGenerateResponse(BaseModel):
    """P3-3 — response for POST /chat/quiz."""

    questions: list[QuizQuestion]
    concepts_covered: list[str] = Field(
        default_factory=list,
        description="Unique atomic concepts across all returned questions (e.g. ['HNSW', 'quantization']).",
    )


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
