"""D9 / Pass 3b §2 — canonical agentic endpoint.

POST /api/v1/agentic/{flow}/chat

The replacement for /api/v1/agents/chat (legacy MOA-driven). Hands
off to AgenticOrchestratorService which orchestrates the full
Supervisor + dispatch + safety pipeline.

Flow parameter (Pass 3b §13.1, anti-pattern note 7): forward
compatibility for different flow configurations later. For D9, accept
"default" and "demo" as valid flows; reject others. The flow value
is currently informational — it doesn't change pipeline behavior in
v1, but lets us route differently in v2 without breaking URL shape.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies.entitlement import require_active_entitlement
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.entitlement import EntitlementContext
from app.services.agentic_orchestrator import (
    AgenticOrchestratorService,
    OrchestratorResult,
)

log = structlog.get_logger().bind(layer="agentic_route")


router = APIRouter(prefix="/agentic", tags=["agentic"])


# Flows accepted in v1. Adding a flow is a config + tests change.
_VALID_FLOWS: frozenset[str] = frozenset({"default", "demo"})


class AgenticChatRequest(BaseModel):
    """Inbound payload for POST /agentic/{flow}/chat."""

    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: uuid.UUID | None = None


class AgenticChatResponse(BaseModel):
    """Outbound shape — projection of OrchestratorResult.

    Trimmed for the client surface: includes the response text,
    the agent that produced it, the conversation/request ids, and
    block flags. Full OrchestratorResult lives in agent_actions for
    the trace endpoint.
    """

    request_id: uuid.UUID
    conversation_id: uuid.UUID
    response: str
    agent_name: str | None
    blocked: bool
    block_reason: str | None
    decline_reason: str | None = None
    suggested_next_action: str | None = None
    duration_ms: int


# Module-level orchestrator instance — Presidio is heavy, build once
# per process. The service is stateless; safe to reuse across requests.
_orchestrator_singleton: AgenticOrchestratorService | None = None


def _get_orchestrator() -> AgenticOrchestratorService:
    """Lazy-built singleton orchestrator.

    Construction triggers SafetyGate.get_default_gate(), which loads
    Presidio + spaCy. The lifespan handler in main.py also calls
    get_default_gate() at startup, so by the time this dependency
    fires the gate is already warm; the lazy build here covers
    cold-test paths.
    """
    global _orchestrator_singleton
    if _orchestrator_singleton is None:
        _orchestrator_singleton = AgenticOrchestratorService()
    return _orchestrator_singleton


@router.post("/{flow}/chat", response_model=AgenticChatResponse)
async def agentic_chat(
    payload: AgenticChatRequest,
    flow: Literal["default", "demo"] = Path(
        ...,
        description="Forward-compat flow selector. v1 accepts 'default' or 'demo'.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    entitlement_ctx: EntitlementContext = Depends(require_active_entitlement),
) -> AgenticChatResponse:
    """Canonical agentic chat entry point.

    Sequence:
      1. Layer 1 — require_active_entitlement raised 402 if user is
         unentitled. We get an EntitlementContext on success.
      2. Orchestrator runs Supervisor + dispatch + safety pipeline.
      3. Result projects to AgenticChatResponse.

    All three entitlement layers are enforced:
      - Layer 1 here (the dependency)
      - Layer 2 inside the Supervisor (filtered available_agents)
      - Layer 3 inside the dispatch layer (fresh re-check)
    """
    if flow not in _VALID_FLOWS:
        # FastAPI's Literal already restricts at validation time; this
        # is defense-in-depth in case the type ever broadens.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown flow {flow!r}; valid: {sorted(_VALID_FLOWS)}",
        )

    orchestrator = _get_orchestrator()

    result: OrchestratorResult = await orchestrator.process_request(
        db=db,
        student_id=current_user.id,
        actor_id=current_user.id,  # student-initiated request
        actor_role="student",
        user_message=payload.message,
        conversation_id=payload.conversation_id,
        flow=flow,
        entitlement_ctx=entitlement_ctx,
    )

    decline_reason = (
        result.decision.decline_reason
        if result.decision is not None and result.decision.action == "decline"
        else None
    )
    suggested_next = (
        result.decision.suggested_next_action
        if result.decision is not None and result.decision.action == "decline"
        else None
    )

    return AgenticChatResponse(
        request_id=result.request_id,
        conversation_id=result.conversation_id,
        response=result.response_text,
        agent_name=result.target_agent,
        blocked=result.blocked,
        block_reason=result.block_reason,
        decline_reason=decline_reason,
        suggested_next_action=suggested_next,
        duration_ms=result.duration_ms,
    )
