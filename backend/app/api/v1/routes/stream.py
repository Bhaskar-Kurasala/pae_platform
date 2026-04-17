# ADD TO main.py: from app.api.v1.routes.stream import router as stream_router
# ADD TO main.py: app.include_router(stream_router, prefix="/api/v1")

"""SSE Streaming Endpoint for agent responses.

Streams tokens from Claude directly to the client without waiting for the full
MOA graph to complete. Uses keyword routing for fast agent classification, then
streams the model response token-by-token.

SSE format:
  data: {"chunk": "token text", "done": false}
  data: {"chunk": "", "done": true}
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

from app.agents.moa import ROUTABLE_AGENTS, _keyword_route
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agent import ChatRequest

log = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents-stream"])

# System prompts per agent type for direct streaming (bypasses full MOA)
_STREAM_SYSTEM_PROMPTS: dict[str, str] = {
    "socratic_tutor": (
        "You are a Socratic tutor for AI engineering. "
        "Guide the student to understanding through questions rather than giving direct answers. "
        "Always end your response with a thoughtful question."
    ),
    "coding_assistant": (
        "You are an expert AI engineering coding assistant. "
        "Provide clear, production-quality code with type hints, structlog logging, and async patterns. "
        "Use inline PR-style comments to explain suggestions."
    ),
    "student_buddy": (
        "You are a student buddy for AI engineering learners. "
        "Provide concise, clear explanations under 200 words. Use analogies and simple language."
    ),
    "career_coach": (
        "You are an expert AI Engineering Career Coach. "
        "Be direct, specific, and actionable. Use numbered lists for plans."
    ),
    "resume_reviewer": (
        "You are a resume reviewer for AI engineering roles. "
        "Be brutally honest. Provide specific before/after improvements."
    ),
    "billing_support": (
        "You are a helpful billing support agent for the PAE Platform. "
        "Answer questions about subscriptions concisely. "
        "Redirect financial decisions to support@pae.dev."
    ),
    "default": (
        "You are a helpful AI engineering learning assistant. "
        "Answer clearly and accurately."
    ),
}


def _get_system_prompt(agent_name: str) -> str:
    return _STREAM_SYSTEM_PROMPTS.get(agent_name, _STREAM_SYSTEM_PROMPTS["default"])


def _build_streaming_llm() -> ChatAnthropic:
    return ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",
        anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
        max_tokens=1024,
        streaming=True,
    )


async def _token_generator(
    message: str,
    agent_name: str,
    conversation_history: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted token chunks from Claude's stream."""
    llm = _build_streaming_llm()
    system_prompt = _get_system_prompt(agent_name)

    messages: list[Any] = [SystemMessage(content=system_prompt)]

    # Include last 6 turns from conversation history
    for turn in conversation_history[-6:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))

    messages.append(HumanMessage(content=message))

    try:
        async for chunk in llm.astream(messages):
            token = str(chunk.content) if hasattr(chunk, "content") else ""
            if token:
                payload = json.dumps({"chunk": token, "done": False})
                yield f"data: {payload}\n\n"

        # Signal completion
        yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"

    except Exception as exc:
        log.warning("stream.token_generator_error", error=str(exc))
        error_payload = json.dumps({"chunk": f"\n[Stream error: {exc}]", "done": True})
        yield f"data: {error_payload}\n\n"


@router.post("/stream")
@limiter.limit("30/minute")
async def stream_chat(
    request: Request,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream agent response tokens via Server-Sent Events.

    Uses keyword routing to classify the request, then streams directly from
    Claude without the full MOA LangGraph pipeline overhead.

    Rate limited to 30/minute per user.
    """
    message = payload.message
    explicit_agent = payload.agent_name

    # Classify intent (keyword route first, then default)
    if explicit_agent and explicit_agent in ROUTABLE_AGENTS:
        agent_name = explicit_agent
    else:
        agent_name = _keyword_route(message) or "socratic_tutor"

    log.info(
        "stream.request",
        student_id=str(current_user.id),
        agent=agent_name,
        message_preview=message[:60],
    )

    # Load conversation history from context if provided
    conversation_history: list[dict[str, Any]] = []
    if payload.context and isinstance(payload.context.get("conversation_history"), list):
        conversation_history = payload.context["conversation_history"]

    return StreamingResponse(
        _token_generator(message, agent_name, conversation_history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Agent-Name": agent_name,
        },
    )
