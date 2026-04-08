from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agent import AgentInfo, ChatRequest, ChatResponse
from app.services.agent_orchestrator import AgentOrchestratorService

router = APIRouter(prefix="/agents", tags=["agents"])


def get_orchestrator(db: AsyncSession = Depends(get_db)) -> AgentOrchestratorService:
    return AgentOrchestratorService(db)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    orchestrator: AgentOrchestratorService = Depends(get_orchestrator),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    result = await orchestrator.chat(
        student_id=str(current_user.id),
        message=payload.message,
        conversation_id=payload.conversation_id,
        agent_name=payload.agent_name,
        context=payload.context,
    )
    return result


@router.get("/list", response_model=list[AgentInfo])
async def list_agents() -> list[dict[str, str]]:
    from app.agents.registry import _ensure_registered, list_agents

    _ensure_registered()
    return list_agents()
