import uuid
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    agent_name: str | None = None  # None → MOA auto-routes
    message: str
    # UUID for the persisted chat (P0-2). Optional: when omitted the stream
    # endpoint creates a new conversation and returns its id in the first
    # SSE event. Kept nullable so existing callers (Redis-backed orchestrator
    # in `/agents/chat`) can keep passing a free-form string via JSON and
    # have Pydantic validate it as a UUID.
    conversation_id: uuid.UUID | None = None
    context: dict[str, Any] | None = None
    # P1-6 — optional list of pending attachment ids to bind to this user
    # turn. Capped at the same value the service enforces (4 per message).
    attachment_ids: list[uuid.UUID] | None = Field(default=None, max_length=4)


class ChatResponse(BaseModel):
    response: str
    agent_name: str
    evaluation_score: float | None = None
    conversation_id: str | None = None
    error: bool | None = None


class AgentInfo(BaseModel):
    name: str
    description: str
