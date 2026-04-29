from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deprecated import deprecated
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agent import AgentInfo, ChatRequest, ChatResponse
from app.services.agent_orchestrator import AgentOrchestratorService

log = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents"])


def get_orchestrator(db: AsyncSession = Depends(get_db)) -> AgentOrchestratorService:
    return AgentOrchestratorService(db)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    orchestrator: AgentOrchestratorService = Depends(get_orchestrator),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        result = await orchestrator.chat(
            student_id=str(current_user.id),
            message=payload.message,
            # Orchestrator expects a str (Redis cache key); schema is UUID for
            # the P0-2 persistence layer, so stringify at the boundary.
            conversation_id=(
                str(payload.conversation_id) if payload.conversation_id else None
            ),
            agent_name=payload.agent_name,
            context=payload.context,
        )
    except Exception as exc:
        log.exception("agent_chat_error", error=str(exc))
        return {
            "response": "I encountered an issue. Please try again later.",
            "agent_name": "system",
            "conversation_id": None,
            "error": True,
        }
    return result


@router.get("/list", response_model=list[AgentInfo])
@deprecated(sunset="2026-07-01", reason="no live UI caller -- admin lists via /admin/agents/health")
async def list_agents(
    current_user: User = Depends(get_current_user),
) -> list[dict[str, str]]:
    from app.agents.registry import _ensure_registered
    from app.agents.registry import list_agents as _list_agents

    _ensure_registered()
    return _list_agents()
