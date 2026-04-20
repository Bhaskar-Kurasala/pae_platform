"""Pydantic schemas for the notebook endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotebookEntryCreate(BaseModel):
    message_id: str
    conversation_id: str
    content: str
    title: str | None = None
    source_type: str | None = "chat"
    topic: str | None = None


class NotebookEntryUpdate(BaseModel):
    """PATCH payload — only fields the student can edit."""
    user_note: str | None = None
    title: str | None = None
    topic: str | None = None


class NotebookEntryOut(BaseModel):
    id: str
    message_id: str
    conversation_id: str
    content: str
    title: str | None
    user_note: str | None
    source_type: str | None
    topic: str | None
    last_reviewed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
