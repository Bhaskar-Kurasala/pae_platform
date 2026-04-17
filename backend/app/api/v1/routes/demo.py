# ADD TO main.py: from app.api.v1.routes.demo import router as demo_router
# ADD TO main.py: app.include_router(demo_router, prefix="/api/v1")

"""Public demo endpoint for the landing page live demo widget.

No authentication required. Rate limited to 5/hour per IP.
Only uses the socratic_tutor agent. Max 200 chars per message.
"""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.agents.base_agent import AgentState
from app.core.rate_limit import limiter
from app.schemas.agent import ChatResponse

log = structlog.get_logger()

router = APIRouter(prefix="/demo", tags=["demo"])

_DEMO_STUDENT_ID = "demo-user-landing-page"
_MAX_MESSAGE_LENGTH = 200


class DemoChatRequest(BaseModel):
    message: str = Field(..., max_length=_MAX_MESSAGE_LENGTH)


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("5/hour")
async def demo_chat(
    request: Request,
    payload: DemoChatRequest,
) -> dict[str, Any]:
    """Public demo endpoint — no auth required.

    Only uses the `socratic_tutor` agent. Rate limited to 5/hour per IP
    to prevent abuse. Max 200 characters per message.

    This endpoint powers the landing page live demo widget.
    """
    message = payload.message.strip()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message cannot be empty.",
        )

    log.info(
        "demo.chat.request",
        message_preview=message[:60],
        ip=request.client.host if request.client else "unknown",
    )

    # Import here to avoid circular imports at module load time
    from app.agents.registry import _ensure_registered, get_agent

    _ensure_registered()

    try:
        agent = get_agent("socratic_tutor")
        state = AgentState(
            student_id=_DEMO_STUDENT_ID,
            task=message,
            context={},
        )
        result = await agent.run(state)
        response_text = result.response or "I couldn't generate a response. Please try again."
        eval_score = result.evaluation_score

    except Exception as exc:
        log.warning("demo.chat.error", error=str(exc))
        response_text = (
            "Welcome to the PAE Platform demo! "
            "I'm a Socratic tutor specialising in production AI engineering. "
            "What concept would you like to explore? "
            "Try asking about RAG, LangGraph, or production deployment patterns."
        )
        eval_score = None

    return {
        "response": response_text,
        "agent_name": "socratic_tutor",
        "evaluation_score": eval_score,
        "conversation_id": None,
    }
