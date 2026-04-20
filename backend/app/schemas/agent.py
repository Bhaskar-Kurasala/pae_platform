import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.context import ContextRef


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
    # P1-7 — optional list of kind-tagged context refs (submission / lesson /
    # exercise). Server-resolved and prepended to the user turn; capped at 3
    # so a chatty client can't flood the prompt.
    context_refs: list[ContextRef] | None = Field(default=None, max_length=3)
    # Long-answer continuation: when set, the stream will fetch the truncated
    # assistant message by this id and instruct the LLM to continue from where
    # it left off, appending seamlessly to the same bubble.
    continue_from_message_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    response: str
    agent_name: str
    evaluation_score: float | None = None
    conversation_id: str | None = None
    error: bool | None = None


class AgentInfo(BaseModel):
    name: str
    description: str
