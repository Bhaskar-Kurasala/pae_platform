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

import contextlib
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
from app.services.disagreement_service import (
    DISAGREEMENT_OVERLAY,
    maybe_log_disagreement,
)
from app.services.intent_before_debug_service import (
    INTENT_BEFORE_DEBUG_OVERLAY,
    should_apply_intent_overlay,
)
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

# Graded socratic overlays (3A-3). Intensity is chosen by the student in the
# preferences slider; the strict overlay above remains for level 3 so the
# existing test coverage still passes.
_SOCRATIC_GENTLE_OVERLAY = (
    "\n\n---\nUser prefers GENTLE socratic nudging. Prefer one short guiding "
    "question at the top of your reply, then give a direct answer if appropriate. "
    "Aim for about one question for every two direct statements."
)

_SOCRATIC_STANDARD_OVERLAY = (
    "\n\n---\nUser prefers STANDARD socratic coaching. Lead with a question that "
    "surfaces the student's current understanding, then help them work toward the "
    "answer with hints — give direct answers only after they've attempted reasoning, "
    "or when the question is purely factual."
)


def _socratic_overlay_for(level: int) -> str | None:
    """Map 0-3 to the right overlay string (or `None` for off)."""
    if level <= 0:
        return None
    if level == 1:
        return _SOCRATIC_GENTLE_OVERLAY
    if level == 2:
        return _SOCRATIC_STANDARD_OVERLAY
    return _SOCRATIC_STRICT_OVERLAY

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
    socratic_level: int = 0,
    user_id: uuid.UUID | None = None,
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

        # Graded intensity takes precedence over the legacy strict toggle.
        # tutor_mode is still honored at level 0 so a user on an old client
        # that only writes tutor_mode="socratic_strict" still gets strict.
        overlay = _socratic_overlay_for(socratic_level)
        if overlay is None and tutor_mode == "socratic_strict":
            overlay = _SOCRATIC_STRICT_OVERLAY
        if overlay:
            system_prompt += overlay

        if scaffolding is not None:
            system_prompt += (
                "\n\n---\nScaffolding guidance for this student on the skill in "
                f"scope (internal — do not quote back): level={scaffolding.label}, "
                f"effective_confidence={scaffolding.effective_confidence:.2f}"
                + (" (decayed — skill has faded from lack of practice)" if scaffolding.decayed else "")
                + f".\n{scaffolding.prompt_fragment}"
            )

        # Intent-before-debug (P3 3A-5): if the student pasted an error and
        # we routed to a coding agent, force the tutor to ask about intent
        # before diving in. The overlay is additive to the socratic one so
        # both rules can compose.
        if should_apply_intent_overlay(agent_name, message):
            system_prompt += INTENT_BEFORE_DEBUG_OVERLAY
            log.info(
                "tutor.intent_before_debug_triggered",
                agent=agent_name,
                message_preview=message[:80],
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

        # Disagreement rule (P3 3A-6): always on for every tutor turn. The
        # rule is cheap to state and the cost of a yes-machine is high.
        system_prompt += DISAGREEMENT_OVERLAY

        messages: list[Any] = [SystemMessage(content=system_prompt)]

        for turn in conversation_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=message))

        # Buffer the full reply so we can scan for disagreement markers after
        # streaming completes (P3 3A-6). Cap the buffer defensively — only the
        # beginning matters for the scan, and unbounded concatenation on a
        # long reply wastes memory.
        reply_chunks: list[str] = []
        reply_total = 0
        _REPLY_SCAN_CAP = 4000

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
                if reply_total < _REPLY_SCAN_CAP:
                    reply_chunks.append(token)
                    reply_total += len(token)
                payload = json.dumps({"chunk": token, "done": False})
                yield f"data: {payload}\n\n"

        # Signal completion
        yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"

        # Post-stream: scan for a disagreement marker and persist a
        # misconception row when the student made a factual claim. Best
        # effort — a failure here must never surface to the client because
        # the `done: true` event already shipped.
        if user_id is not None and reply_chunks:
            full_reply = "".join(reply_chunks)
            with contextlib.suppress(Exception):
                async with AsyncSessionLocal() as log_session:
                    logged = await maybe_log_disagreement(
                        log_session,
                        user_id=user_id,
                        student_message=message,
                        tutor_reply=full_reply,
                    )
                    if logged is not None:
                        await log_session.commit()

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
    socratic_level = 0
    student_context_block: str | None = None
    async with AsyncSessionLocal() as session:
        prefs = await PreferencesService(session).get_or_create(current_user.id)
        tutor_mode = prefs.tutor_mode
        socratic_level = getattr(prefs, "socratic_level", 0) or 0
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
            socratic_level,
            current_user.id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Agent-Name": agent_name,
            "X-Scaffolding-Level": scaffolding.label if scaffolding else "none",
            "X-Tutor-Mode": tutor_mode,
            "X-Socratic-Level": str(socratic_level),
        },
    )
