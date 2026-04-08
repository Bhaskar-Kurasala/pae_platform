from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    agent_name: str | None = None  # None → MOA auto-routes
    message: str
    conversation_id: str | None = None
    context: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    response: str
    agent_name: str
    evaluation_score: float
    conversation_id: str


class AgentInfo(BaseModel):
    name: str
    description: str
