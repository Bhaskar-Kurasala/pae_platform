"""Pydantic schemas for the notebook endpoints (P3-4).

`NotebookEntryCreate` — request body for POST /api/v1/chat/notebook.
`NotebookEntryOut`    — response shape for all three endpoints.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotebookEntryCreate(BaseModel):
    message_id: str
    conversation_id: str
    content: str
    title: str | None = None


class NotebookEntryOut(BaseModel):
    id: str
    message_id: str
    conversation_id: str
    content: str
    title: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
