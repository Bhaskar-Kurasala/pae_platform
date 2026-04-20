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
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.llm_factory import build_llm
from app.agents.moa import ROUTABLE_AGENTS, _keyword_route, keyword_route_with_reason
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agent import ChatRequest
from app.services.attachment_service import AttachmentService
from app.services.attachment_storage import build_default_storage
from app.services.chat_service import ChatService
from app.services.confidence_service import CONFIDENCE_CALIBRATION_OVERLAY
from app.services.context_attach_service import ContextAttachService
from app.services.disagreement_service import (
    DISAGREEMENT_OVERLAY,
    maybe_log_disagreement,
)
from app.services.honesty_service import HONESTY_OVERLAY, detect_honesty_hedge
from app.services.intent_before_debug_service import (
    INTENT_BEFORE_DEBUG_OVERLAY,
    should_apply_intent_overlay,
)
from app.services.misconception_service import (
    detect_misconceptions,
)
from app.services.misconception_service import (
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

# P2-7 — The stream rate limit is read both for building response headers on
# the happy path AND by the RateLimitExceeded handler in main.py to compute
# Retry-After seconds. Centralizing the string keeps the two paths in sync.
# Keeping the historical 30/minute so existing tests and rate-limiter fixtures
# (backend/tests/conftest.py:reset_rate_limiter) keep working unchanged.
STREAM_RATE_LIMIT = "30/minute"


def _rate_limit_headers(request: Request) -> dict[str, str]:
    """Compute ``X-RateLimit-*`` + ``Retry-After`` headers from slowapi state.

    P2-7 — slowapi stores the matching ``RateLimitItem`` + key list on
    ``request.state.view_rate_limit`` once ``@limiter.limit(...)`` has run its
    pre-flight check. ``limiter.get_window_stats`` returns ``(reset_epoch,
    remaining)`` which is exactly what we need to tell the client how many
    stream calls are left and when the window resets. We build a dict rather
    than mutating a response directly because ``StreamingResponse`` wants its
    headers passed at construction time. Defensive — any failure returns an
    empty dict so the stream response still ships.
    """
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit is None:
        return {}
    try:
        item, key_parts = view_limit
        reset_epoch, remaining = limiter.limiter.get_window_stats(item, *key_parts)
    except Exception as exc:  # pragma: no cover — defensive path
        log.warning("stream.rate_limit_header_compute_failed", error=str(exc))
        return {}
    retry_after = max(0, int(reset_epoch - time.time()))
    return {
        "X-RateLimit-Limit": str(item.amount),
        "X-RateLimit-Remaining": str(max(0, int(remaining))),
        "X-RateLimit-Reset": str(int(reset_epoch)),
        "Retry-After": str(retry_after),
    }


router = APIRouter(prefix="/agents", tags=["agents-stream"])

# P1-2 — regenerate lives under /chat/messages/{id}/regenerate to match the
# rest of the chat persistence surface even though the implementation reuses
# the SSE token generator. Mounted alongside the streaming router in main.py.
chat_stream_router = APIRouter(prefix="/chat", tags=["chat-stream"])

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
    conversation_id: uuid.UUID | None = None,
    parent_user_message_id: uuid.UUID | None = None,
    extra_first_event: dict[str, Any] | None = None,
    user_content: str | list[dict[str, Any]] | None = None,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted token chunks from Claude's stream."""
    # Track partial content so we can still persist the assistant turn when
    # the stream errors mid-way — prevents corrupt conversations where only
    # the user message got saved.
    reply_chunks: list[str] = []
    reply_total = 0
    _REPLY_SCAN_CAP = 4000
    # P2-5 — hover-panel metadata. `start_time` is stamped before the first
    # yield so latency reflects wall-clock from generator entry; `first_token_ms`
    # is set on the first non-empty token; `input_tokens` / `output_tokens` are
    # pulled from the langchain chunk's `usage_metadata` (streaming providers
    # emit them on the final chunk). `model_id` falls back to the configured
    # settings value when the chunk doesn't carry `response_metadata.model`.
    start_time = time.monotonic()
    first_token_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_id: str | None = None
    try:
        # Emit agent identity + conversation id immediately so the UI can
        # (a) show who's responding and (b) capture the conv id for follow-up
        # turns. P0-2 adds `conversation_id`; agent_name stays for back-compat
        # with existing clients that key off it.
        first_event: dict[str, Any] = {
            "agent_name": agent_name,
            "chunk": "",
            "done": False,
        }
        if conversation_id is not None:
            first_event["conversation_id"] = str(conversation_id)
        if extra_first_event:
            first_event.update(extra_first_event)
        yield f"data: {json.dumps(first_event)}\n\n"

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

        # Confidence calibration (P3 3A-7): tutor decides when to ask,
        # based on conversation-history awareness from the directive.
        system_prompt += CONFIDENCE_CALIBRATION_OVERLAY

        # Honesty rule (P3 3A-8): when not confident, say so rather than
        # fabricating. We don't rewrite the reply — we just observe via
        # the post-stream hedge detector below.
        system_prompt += HONESTY_OVERLAY

        messages: list[Any] = [SystemMessage(content=system_prompt)]

        for turn in conversation_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        # P1-6 — if the caller assembled a content-block list (images +
        # fenced code-block prefix), use it verbatim. Otherwise fall back to
        # the plain-text turn so the legacy path stays byte-identical.
        final_content: str | list[dict[str, Any]] = (
            user_content if user_content is not None else message
        )
        messages.append(HumanMessage(content=final_content))

        # Buffer the full reply so we can scan for disagreement markers after
        # streaming completes (P3 3A-6). Cap the buffer defensively — only the
        # beginning matters for the scan, and unbounded concatenation on a
        # long reply wastes memory. (reply_chunks is declared above so an
        # exception inside the loop still leaves the partial content available
        # to the post-stream persistence block.)

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
            # P2-5 — scrape token usage + model id from each chunk. langchain
            # streaming providers accumulate counts in `usage_metadata`, usually
            # stamping final totals on the last chunk. `response_metadata.model`
            # carries the concrete model id the provider resolved to.
            chunk_usage = getattr(chunk, "usage_metadata", None)
            if isinstance(chunk_usage, dict):
                if chunk_usage.get("input_tokens") is not None:
                    input_tokens = int(chunk_usage["input_tokens"])
                if chunk_usage.get("output_tokens") is not None:
                    output_tokens = int(chunk_usage["output_tokens"])
            chunk_resp_meta = getattr(chunk, "response_metadata", None)
            if isinstance(chunk_resp_meta, dict):
                model_in_meta = chunk_resp_meta.get("model") or chunk_resp_meta.get(
                    "model_name"
                )
                if isinstance(model_in_meta, str) and model_in_meta:
                    model_id = model_in_meta
            if token:
                if first_token_ms is None:
                    first_token_ms = int((time.monotonic() - start_time) * 1000)
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

            # Honesty hedge telemetry (P3 3A-8): observe when the tutor
            # actually admitted uncertainty so we can track the rule
            # firing — no DB writes, just a structured log event.
            hedge = detect_honesty_hedge(full_reply)
            if hedge is not None:
                log.info(
                    "tutor.honesty_hedge_triggered",
                    user_id=str(user_id),
                    agent=agent_name,
                    marker=hedge.marker,
                )

    except Exception as exc:
        log.warning("stream.token_generator_error", error=str(exc))
        error_payload = json.dumps({"chunk": f"\n[Stream error: {exc}]", "done": True})
        yield f"data: {error_payload}\n\n"
    finally:
        # P0-2: persist the assistant turn — even on partial/error streams —
        # so the conversation isn't left asymmetric (user msg saved, assistant
        # missing). Best-effort; never raise to the client because the stream
        # has already flushed `done: true`.
        # P2-5 — compute total duration at the last possible moment so it
        # reflects wall-clock through stream completion + the finally: hook.
        # When the provider didn't hand us a concrete model, fall back to the
        # configured default so the hover panel still has something to show.
        if conversation_id is not None and reply_chunks:
            full_reply = "".join(reply_chunks)
            total_duration_ms = int((time.monotonic() - start_time) * 1000)
            resolved_model = model_id or (
                settings.minimax_model
                if getattr(settings, "minimax_api_key", None)
                else "claude-sonnet-4-6"
            )
            with contextlib.suppress(Exception):
                async with AsyncSessionLocal() as persist_session:
                    await ChatService(persist_session).record_assistant_message(
                        conversation_id,
                        full_reply,
                        agent_name=agent_name,
                        parent_id=parent_user_message_id,
                        first_token_ms=first_token_ms,
                        total_duration_ms=total_duration_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=resolved_model,
                    )
                    await persist_session.commit()


@router.post("/stream")
@limiter.limit(STREAM_RATE_LIMIT)
async def stream_chat(
    request: Request,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream agent response tokens via Server-Sent Events.

    Uses keyword routing to classify the request, then streams directly from
    Claude without the full MOA LangGraph pipeline overhead.

    Rate limited per ``STREAM_RATE_LIMIT``. Response carries
    ``X-RateLimit-Remaining`` + ``Retry-After`` so the UI can surface a
    "messages left" pill and honour backoff without guessing (P2-7).
    """
    message = payload.message
    explicit_agent = payload.agent_name

    # Classify intent (keyword route first, then default).
    # P2-4 — capture WHY we picked the agent so the UI can render
    # "Routed to Tutor · keyword:explain · change" on the first event.
    routing_reason: str | None
    if explicit_agent and explicit_agent in ROUTABLE_AGENTS:
        agent_name = explicit_agent
        routing_reason = "user_selected"
    else:
        kw = keyword_route_with_reason(message)
        if kw is not None:
            agent_name = kw[0]
            routing_reason = f"keyword:{kw[1]}"
        else:
            agent_name = "socratic_tutor"
            routing_reason = "default_fallback"

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
    persisted_conversation_id: uuid.UUID | None = None
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

        # P0-2: resolve-or-create the persisted conversation and save the user
        # message BEFORE the stream starts. Ownership mismatch raises 404
        # here so the client gets a proper status code instead of mid-stream
        # failure noise. We commit inside this block so a failure later in
        # the generator (post-yield) can't roll back the user-turn write.
        chat_service = ChatService(session)
        conversation = await chat_service.ensure_conversation_for_stream(
            conversation_id=payload.conversation_id,
            user_id=current_user.id,
            agent_name=agent_name,
            first_message=message,
        )
        persisted_conversation_id = conversation.id
        user_msg = await chat_service.record_user_message(conversation, message)
        persisted_user_message_id = user_msg.id
        await chat_service.touch(conversation)

        # P1-6 — resolve any pending attachments, bind them to the freshly
        # inserted user message, and pre-load their bytes into Anthropic
        # content blocks for the LLM call below. Ownership + per-message cap
        # are enforced by the service; raises 404 for unknown/foreign ids
        # before the stream starts. `user_content` stays None when there are
        # no attachments, so the existing text-only path is untouched.
        user_content: str | list[dict[str, Any]] | None = None
        if payload.attachment_ids:
            attachment_service = AttachmentService(
                session, build_default_storage()
            )
            pending = await attachment_service.verify_and_fetch_pending(
                user_id=current_user.id, ids=payload.attachment_ids
            )
            await attachment_service.bind_to_message(
                pending, persisted_user_message_id
            )
            blocks = await attachment_service.build_claude_content_blocks(
                pending, text_message=message
            )
            # Only pass through the block list — if the service short-circuited
            # to a bare string (no attachments actually resolved) we fall back
            # to the plain-text path below.
            if isinstance(blocks, list):
                user_content = blocks

        # P1-7 — resolve context refs (submission / lesson / exercise) into a
        # markdown prefix and splice it ahead of the user's typed message.
        # Keeps the attach mechanism independent of P1-6's storage-backed
        # attachments; ownership is enforced inside the service (404 on a
        # foreign submission ref).
        if payload.context_refs:
            ctx_service = ContextAttachService(session)
            prefix = await ctx_service.build_prefix(
                user_id=current_user.id, refs=payload.context_refs
            )
            if prefix:
                if isinstance(user_content, list):
                    # Splice prefix into the final text block so image blocks
                    # (if any) still lead the list.
                    spliced = False
                    for block in user_content:
                        if block.get("type") == "text":
                            block["text"] = (
                                prefix + "\n\n" + block.get("text", "")
                            )
                            spliced = True
                            break
                    if not spliced:
                        user_content.append(
                            {"type": "text", "text": prefix}
                        )
                else:
                    # No attachments — prepend to the plain message and pass
                    # through the string path (cheapest, LLM-friendly).
                    message = prefix + "\n\n" + message

        await session.commit()

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
            persisted_conversation_id,
            persisted_user_message_id,
            {"routing_reason": routing_reason} if routing_reason else None,
            user_content,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Agent-Name": agent_name,
            "X-Conversation-Id": str(persisted_conversation_id),
            "X-Scaffolding-Level": scaffolding.label if scaffolding else "none",
            "X-Tutor-Mode": tutor_mode,
            "X-Socratic-Level": str(socratic_level),
            "X-Routing-Reason": routing_reason or "unknown",
            # P2-7 — rate-limit awareness. Merged last so the computed values
            # override any accidental duplicate keys above.
            **_rate_limit_headers(request),
        },
    )


# ---------------------------------------------------------------------------
# Regenerate (P1-2)
# ---------------------------------------------------------------------------


@chat_stream_router.post("/messages/{assistant_message_id}/regenerate")
@limiter.limit(STREAM_RATE_LIMIT)
async def regenerate_assistant_message(
    request: Request,
    assistant_message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Regenerate an assistant reply, keeping the prior version(s) as siblings.

    Validates ownership + message role, rebuilds the history slice up to and
    including the user turn that prompted the reply, and streams a fresh
    assistant message via the shared `_token_generator` so the frontend can
    reuse the SSE plumbing from `use-stream.ts`. The new row is persisted in
    the generator's `finally:` block with `parent_id` set to the user
    message id — that's what makes the set of assistant messages with the
    same `parent_id` the "siblings" behind the <1/N> navigator.

    P2-4 — accepts an optional JSON body: ``{agent_override: "<agent>"}``.
    When present AND the name is in ``ROUTABLE_AGENTS``, the regenerate
    runs under that agent instead of re-using the original assistant's
    `agent_name`. Unknown overrides are ignored (fall back to the
    original-agent path) rather than 422 — the UI is authoritative for
    validation and we prefer a degraded-but-successful regenerate over a
    hard error from a stale agent list.

    Returns 404 on a missing or foreign message; 400 if the target isn't
    an assistant row.
    """
    # P2-4 — optional body. Read defensively because the legacy client
    # (pre-P2-4) POSTs with no body at all; FastAPI would 422 if we
    # required a Pydantic model here.
    # P3-1 — also accepts explain_style for the "Explain differently" feature.
    agent_override: str | None = None
    explain_style: str | None = None
    _VALID_EXPLAIN_STYLES = {"simpler", "more_rigorous", "via_analogy", "show_code"}
    try:
        body = await request.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        raw_override = body.get("agent_override")
        if isinstance(raw_override, str) and raw_override.strip():
            agent_override = raw_override.strip()
        raw_style = body.get("explain_style")
        if isinstance(raw_style, str) and raw_style.strip() in _VALID_EXPLAIN_STYLES:
            explain_style = raw_style.strip()

    conversation_history: list[dict[str, Any]] = []
    parent_msg_id: uuid.UUID
    conversation_id: uuid.UUID
    agent_name: str
    routing_reason: str = "regenerate"
    scaffolding: ScaffoldingLevel | None = None
    tutor_mode = "standard"
    socratic_level = 0
    student_context_block: str | None = None

    async with AsyncSessionLocal() as session:
        chat_service = ChatService(session)
        assistant_msg, parent_msg, history_rows = await chat_service.prepare_regenerate(
            assistant_message_id=assistant_message_id,
            user_id=current_user.id,
        )
        conversation_id = assistant_msg.conversation_id
        parent_msg_id = parent_msg.id
        # P2-4 — user-picked override wins when valid; else fall back to
        # the original resolution chain (original agent → conversation
        # agent → keyword route → socratic_tutor default).
        if agent_override and agent_override in ROUTABLE_AGENTS:
            agent_name = agent_override
            routing_reason = "user_override"
        else:
            agent_name = (
                assistant_msg.agent_name
                or (await chat_service.repo.get_conversation(conversation_id)).agent_name  # type: ignore[union-attr]
                or _keyword_route(parent_msg.content)
                or "socratic_tutor"
            )
            routing_reason = "regenerate"
        if agent_name not in ROUTABLE_AGENTS and agent_name not in _STREAM_SYSTEM_PROMPTS:
            agent_name = "socratic_tutor"

        # Build the history payload the same way the frontend does on a
        # normal turn — {role, content} pairs for every turn strictly before
        # the parent user message. The LLM consumer caps at the last 6
        # entries anyway.
        for row in history_rows:
            if row.id == parent_msg.id:
                continue
            if row.role not in ("user", "assistant"):
                continue
            if not row.content:
                continue
            conversation_history.append(
                {"role": row.role, "content": row.content}
            )

        # Preferences + student context mirror the normal stream path so the
        # regenerated reply gets the same socratic overlays, scaffolding,
        # etc. Student context failure must not block regeneration.
        prefs = await PreferencesService(session).get_or_create(current_user.id)
        tutor_mode = prefs.tutor_mode
        socratic_level = getattr(prefs, "socratic_level", 0) or 0
        try:
            student_context_block, _missing = await build_context_block(
                session, current_user.id
            )
        except Exception as exc:
            log.warning("regenerate.student_context_failed", error=str(exc))
            student_context_block = None

    log.info(
        "stream.regenerate_request",
        student_id=str(current_user.id),
        assistant_message_id=str(assistant_message_id),
        parent_user_message_id=str(parent_msg_id),
        agent=agent_name,
    )

    # P3-1 — when the user picks an "Explain differently" style, append a
    # free-text hint to the task. The agents treat task as plain text so this
    # requires no schema changes downstream.
    task_with_hint = parent_msg.content
    if explain_style:
        task_with_hint = f"{parent_msg.content}\n\n[EXPLAIN_STYLE: {explain_style}]"

    return StreamingResponse(
        _token_generator(
            task_with_hint,
            agent_name,
            conversation_history,
            None,  # code_context — regenerate doesn't re-read the editor
            scaffolding,
            tutor_mode,
            student_context_block,
            socratic_level,
            current_user.id,
            conversation_id,
            parent_msg_id,
            {
                "regenerated_from": str(assistant_message_id),
                "routing_reason": routing_reason,
            },
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Agent-Name": agent_name,
            "X-Conversation-Id": str(conversation_id),
            "X-Regenerated-From": str(assistant_message_id),
            "X-Routing-Reason": routing_reason,
            # P2-7 — same rate-limit awareness as the main stream endpoint.
            **_rate_limit_headers(request),
        },
    )
