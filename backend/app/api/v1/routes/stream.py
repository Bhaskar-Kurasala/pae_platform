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
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.llm_factory import build_llm
from app.agents.moa import ROUTABLE_AGENTS, _keyword_route
from app.core.database import AsyncSessionLocal
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agent import ChatRequest
from app.services.misconception_service import (
    detect_misconceptions,
    format_overlay as format_misconception_overlay,
)
from app.services.preferences_service import PreferencesService
from app.services.scaffolding_service import ScaffoldingLevel, load_level
from app.services.student_context_service import build_context_block

_SOCRATIC_STRICT_OVERLAY = (
    "\n\n---\nUser has enabled SOCRATIC STRICT mode. Under this mode you MUST NOT "
    "give direct answers, solution code, definitions, or step-by-step instructions. "
    "You may only respond with thoughtful questions that help the student reason "
    "toward the answer themselves. If the student insists on a direct answer, "
    "acknowledge their frustration briefly and then ask another question. "
    "Rule of thumb: every response ends with a '?'. No exceptions."
)

log = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents-stream"])

# System prompts per agent type for direct streaming (bypasses full MOA)
_FORMATTING_RULES = (
    " Format responses using Markdown: use ## and ### for sections, "
    "**bold** for key terms, bullet lists for enumerations, numbered lists for steps, "
    "and fenced code blocks with a language tag (e.g. ```python) for all code samples. "
    "Never use ASCII art, box-drawing characters, or plain-text diagrams. "
    "Never use <br> or HTML tags. Keep responses focused and well-structured."
)

_STUDIO_SYSTEM_PROMPT = (
    "You are the Studio tutor — a context-aware coding coach. "
    "You can see the student's current code in the editor. "
    "Always ground your feedback in the specific code shown; quote line numbers and "
    "reference identifiers from their code. "
    "Before giving a solution, ask what they have already tried. "
    "If the code has obvious bugs, point to the exact line. "
    "Prefer guiding questions over full rewrites unless the student explicitly asks."
    + _FORMATTING_RULES
)

_STREAM_SYSTEM_PROMPTS: dict[str, str] = {
    "studio_tutor": _STUDIO_SYSTEM_PROMPT,
    "socratic_tutor": (
        "You are a Socratic tutor for AI engineering. "
        "Guide the student to understanding through well-crafted questions rather than direct answers. "
        "Always end your response with one thoughtful question."
        + _FORMATTING_RULES
    ),
    "coding_assistant": (
        "You are an expert AI engineering coding assistant. "
        "Provide clear, production-quality code with type hints, structlog logging, and async patterns. "
        "For code reviews: list issues as numbered items with severity, then show a corrected code block."
        + _FORMATTING_RULES
    ),
    "adaptive_quiz": (
        "You are an AI engineering quiz coach. "
        "Ask focused questions, give immediate feedback, and explain the correct answer clearly."
        + _FORMATTING_RULES
    ),
    "student_buddy": (
        "You are a student buddy for AI engineering learners. "
        "Provide concise, clear explanations. Use analogies and simple language. Max 200 words."
        + _FORMATTING_RULES
    ),
    "career_coach": (
        "You are an expert AI Engineering Career Coach. "
        "Be direct, specific, and actionable. Use numbered lists for action plans."
        + _FORMATTING_RULES
    ),
    "resume_reviewer": (
        "You are a resume reviewer for AI engineering roles. "
        "Be brutally honest. Provide specific before/after improvements."
        + _FORMATTING_RULES
    ),
    "billing_support": (
        "You are a helpful billing support agent for the PAE Platform. "
        "Answer questions about subscriptions concisely. "
        "Redirect financial decisions to support@pae.dev."
        + _FORMATTING_RULES
    ),
    "default": (
        "You are a helpful AI engineering learning assistant. "
        "Answer clearly and accurately."
        + _FORMATTING_RULES
    ),
}


def _get_system_prompt(agent_name: str) -> str:
    return _STREAM_SYSTEM_PROMPTS.get(agent_name, _STREAM_SYSTEM_PROMPTS["default"])




async def _token_generator(
    message: str,
    agent_name: str,
    conversation_history: list[dict[str, Any]],
    code_context: str | None = None,
    scaffolding: ScaffoldingLevel | None = None,
    tutor_mode: str = "standard",
    student_context_block: str | None = None,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted token chunks from Claude's stream."""
    try:
        # Emit agent identity immediately so UI can show who's responding
        yield f"data: {json.dumps({'agent_name': agent_name, 'chunk': '', 'done': False})}\n\n"

        llm = build_llm()
        system_prompt = _get_system_prompt(agent_name)

        # Baseline student state goes first — scaffolding, socratic overlays, and
        # code context all read better when they have a picture of who's asking.
        if student_context_block:
            system_prompt += "\n\n" + student_context_block

        if tutor_mode == "socratic_strict":
            system_prompt += _SOCRATIC_STRICT_OVERLAY

        if scaffolding is not None:
            system_prompt += (
                "\n\n---\nScaffolding guidance for this student on the skill in "
                f"scope (internal — do not quote back): level={scaffolding.label}, "
                f"effective_confidence={scaffolding.effective_confidence:.2f}"
                + (" (decayed — skill has faded from lack of practice)" if scaffolding.decayed else "")
                + f".\n{scaffolding.prompt_fragment}"
            )

        if code_context:
            system_prompt += (
                "\n\n---\nStudent's current code (Python):\n"
                f"```python\n{code_context}\n```"
            )
            # Mental-model layer: if the AST detector spots patterns that signal
            # a deeper misunderstanding, hint the tutor so it can address the
            # model, not just the line. The overlay is internal — the tutor is
            # told not to quote it back.
            try:
                misc_items = detect_misconceptions(code_context).items
                overlay = format_misconception_overlay(misc_items)
                if overlay:
                    system_prompt += overlay
            except Exception as exc:  # detector must never break the stream
                log.warning("stream.misconception_overlay_failed", error=str(exc))

        messages: list[Any] = [SystemMessage(content=system_prompt)]

        for turn in conversation_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=message))

        async for chunk in llm.astream(messages):
            content = getattr(chunk, "content", "")
            if isinstance(content, list):
                # Extended thinking: extract only text blocks, skip thinking blocks
                token = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                    if not (isinstance(block, dict) and block.get("type") == "thinking")
                )
            else:
                token = str(content)
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
    code_context: str | None = None
    skill_id_raw: str | None = None
    if payload.context:
        if isinstance(payload.context.get("conversation_history"), list):
            conversation_history = payload.context["conversation_history"]
        raw_code = payload.context.get("code")
        if isinstance(raw_code, str) and raw_code.strip():
            # Cap at ~8k chars to avoid token blowups on huge files.
            code_context = raw_code[:8000]
        raw_skill = payload.context.get("skill_id")
        if isinstance(raw_skill, str) and raw_skill.strip():
            skill_id_raw = raw_skill.strip()

    scaffolding: ScaffoldingLevel | None = None
    tutor_mode = "standard"
    student_context_block: str | None = None
    async with AsyncSessionLocal() as session:
        prefs = await PreferencesService(session).get_or_create(current_user.id)
        tutor_mode = prefs.tutor_mode
        if skill_id_raw:
            try:
                skill_uuid = uuid.UUID(skill_id_raw)
            except ValueError:
                log.info("stream.invalid_skill_id", skill_id=skill_id_raw)
            else:
                scaffolding = await load_level(session, current_user.id, skill_uuid)
                log.info(
                    "stream.scaffolding_resolved",
                    user_id=str(current_user.id),
                    skill_id=skill_id_raw,
                    level=scaffolding.label,
                    effective_confidence=scaffolding.effective_confidence,
                    decayed=scaffolding.decayed,
                )
        # Student-state context (P3 3A-1). Build once per request so the tutor
        # can calibrate opening/tone. Failure here must never break the stream
        # — we fall back to no block and keep going.
        try:
            student_context_block, _missing = await build_context_block(
                session, current_user.id
            )
        except Exception as exc:
            log.warning("stream.student_context_failed", error=str(exc))
            student_context_block = None

    return StreamingResponse(
        _token_generator(
            message,
            agent_name,
            conversation_history,
            code_context,
            scaffolding,
            tutor_mode,
            student_context_block,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Agent-Name": agent_name,
            "X-Scaffolding-Level": scaffolding.label if scaffolding else "none",
            "X-Tutor-Mode": tutor_mode,
        },
    )
