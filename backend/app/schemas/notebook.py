"""Pydantic schemas for the notebook endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotebookEntryCreate(BaseModel):
    message_id: str
    conversation_id: str
    content: str
    title: str | None = None
    source_type: str | None = "chat"
    topic: str | None = None
    tags: list[str] = Field(default_factory=list)
    # P-Today2 (2026-04-26) — the student's rewritten note, populated by the
    # SaveNoteModal after they edit the LLM-suggested summary. Stored on the
    # row alongside the raw assistant `content` so we can show "Original" in
    # the detail drawer without losing the rewrite.
    user_note: str | None = None


class NotebookEntryUpdate(BaseModel):
    """PATCH payload — only fields the student can edit."""
    user_note: str | None = None
    title: str | None = None
    topic: str | None = None
    tags: list[str] | None = None


class NotebookEntryOut(BaseModel):
    id: str
    message_id: str
    conversation_id: str
    content: str
    title: str | None
    user_note: str | None
    source_type: str | None
    topic: str | None
    tags: list[str] = Field(default_factory=list)
    last_reviewed_at: datetime | None
    graduated_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotebookSourceCount(BaseModel):
    source: str
    count: int


class NotebookSummaryResponse(BaseModel):
    total: int = 0
    graduated: int = 0
    in_review: int = 0
    graduation_percentage: float = 0.0
    latest_graduated_at: datetime | None = None
    by_source: list[NotebookSourceCount] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class NoteSummarizeRequest(BaseModel):
    """POST body for /chat/notebook/summarize.

    `message_id` is the cache key. `content` is the raw assistant reply
    we're summarizing. `user_question` is the prompt that produced the reply
    (when known) — passing it makes the summary noticeably more on-target,
    but it's optional so non-chat callers (studio, quiz) still work.
    """

    message_id: str
    content: str
    user_question: str | None = None


class NoteSummarizeResponse(BaseModel):
    summary: str
    suggested_tags: list[str] = Field(default_factory=list)
    cached: bool = False
