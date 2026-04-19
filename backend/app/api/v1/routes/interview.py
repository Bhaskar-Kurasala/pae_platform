"""Interview simulation endpoints (P2-10).

Thin controller around InterviewSessionStore + the interviewer system prompt.
Streaming shares the SSE format used elsewhere in the app so the frontend can
reuse its token-reader.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.llm_factory import build_llm
from app.core.rate_limit import limiter
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.models.user import User
from app.services.interview_service import (
    INTERVIEWER_SYSTEM_PROMPT,
    InterviewSessionStore,
    PROBLEM_BANK,
    debrief_system_prompt,
    pick_problem,
)

log = structlog.get_logger()

router = APIRouter(prefix="/interview", tags=["interview"])


def _flatten_llm_content(content: Any) -> str:
    """Normalize Anthropic list-of-dicts content (extended thinking etc.) to text.

    Claude sometimes returns `content` as [{"type": "thinking", ...}, {"type": "text", "text": "..."}]
    rather than a plain string. str() on that yields Python repr, which is useless
    for JSON parsing. Skip thinking blocks and concatenate text chunks.
    """
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "thinking":
                    continue
                text = block.get("text", "")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Return the first balanced {...} JSON object in `text`, or None.

    Tolerates leading/trailing prose the model sometimes emits alongside JSON.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return None
    return None


class StartRequest(BaseModel):
    problem_slug: str | None = None  # optional: let user pick, else auto


class ProblemSummary(BaseModel):
    slug: str
    title: str
    category: str


class StartResponse(BaseModel):
    session_id: str
    problem: ProblemSummary
    prompt: str
    started_at: str


class TurnRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1, max_length=6_000)


class AxisScore(BaseModel):
    score: int
    observation: str


class DebriefResponse(BaseModel):
    overall_verdict: str
    headline: str
    axes: dict[str, AxisScore]
    strongest_moment: str
    biggest_gap: str
    next_focus: str


async def _store() -> InterviewSessionStore:
    redis = await get_redis()
    return InterviewSessionStore(redis)


@router.get("/problems", response_model=list[ProblemSummary])
async def list_problems(
    current_user: User = Depends(get_current_user),
) -> list[ProblemSummary]:
    return [ProblemSummary(slug=p.slug, title=p.title, category=p.category) for p in PROBLEM_BANK]


@router.post("/start", response_model=StartResponse)
async def start(
    payload: StartRequest,
    current_user: User = Depends(get_current_user),
) -> StartResponse:
    if payload.problem_slug:
        problem = next((p for p in PROBLEM_BANK if p.slug == payload.problem_slug), None)
        if problem is None:
            raise HTTPException(status_code=404, detail="Unknown problem slug")
    else:
        problem = pick_problem(current_user.id)

    store = await _store()
    session = await store.create(current_user.id, problem)
    return StartResponse(
        session_id=session.session_id,
        problem=ProblemSummary(slug=problem.slug, title=problem.title, category=problem.category),
        prompt=problem.prompt,
        started_at=session.started_at,
    )


async def _interview_token_stream(
    session_id: str,
    user_message: str,
    user_id: uuid.UUID,
) -> AsyncGenerator[str, None]:
    store = await _store()
    session = await store.get(session_id)
    if session is None or session.user_id != str(user_id):
        yield f"data: {json.dumps({'chunk': '', 'done': True, 'error': 'session not found'})}\n\n"
        return

    problem = next((p for p in PROBLEM_BANK if p.slug == session.problem_slug), None)
    if problem is None:
        yield f"data: {json.dumps({'chunk': '', 'done': True, 'error': 'problem missing'})}\n\n"
        return

    # Record the candidate's message before we stream back.
    await store.append_turn(session_id, "user", user_message)

    system_prompt = (
        INTERVIEWER_SYSTEM_PROMPT
        + f"\n\n---\nThe problem you opened with:\n{problem.prompt}\n"
        + "\nInternal probe directions (do NOT quote):\n"
        + "\n".join(f"- {h}" for h in problem.follow_up_hints)
    )

    messages: list[Any] = [SystemMessage(content=system_prompt)]
    for turn in session.turns:
        role = turn.get("role")
        content = turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    # append_turn() persisted the new user message to Redis, but our local
    # `session` snapshot predates it — add the current turn so the LLM
    # actually sees what the candidate just said.
    messages.append(HumanMessage(content=user_message))

    try:
        llm = build_llm()
        full_response = []
        async for chunk in llm.astream(messages):
            content = getattr(chunk, "content", "")
            if isinstance(content, list):
                token = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                    if not (isinstance(block, dict) and block.get("type") == "thinking")
                )
            else:
                token = str(content)
            if token:
                full_response.append(token)
                yield f"data: {json.dumps({'chunk': token, 'done': False})}\n\n"

        final_text = "".join(full_response)
        await store.append_turn(session_id, "assistant", final_text)
        yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
    except Exception as exc:
        log.warning("interview.stream_error", session_id=session_id, error=str(exc))
        yield f"data: {json.dumps({'chunk': f'[stream error: {exc}]', 'done': True})}\n\n"


@router.post("/stream")
@limiter.limit("20/minute")
async def stream_turn(
    request: Request,
    payload: TurnRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        _interview_token_stream(payload.session_id, payload.message, current_user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_id}/debrief", response_model=DebriefResponse)
async def debrief(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> DebriefResponse:
    store = await _store()
    session = await store.get(session_id)
    if session is None or session.user_id != str(current_user.id):
        raise HTTPException(status_code=404, detail="Session not found")

    problem = next((p for p in PROBLEM_BANK if p.slug == session.problem_slug), None)
    if problem is None:
        raise HTTPException(status_code=500, detail="Problem no longer available")

    if not session.turns:
        raise HTTPException(status_code=400, detail="No turns to debrief")

    transcript_lines = []
    for turn in session.turns:
        role = "Candidate" if turn["role"] == "user" else "Interviewer"
        transcript_lines.append(f"{role}: {turn['content']}")
    transcript = "\n\n".join(transcript_lines)

    llm = build_llm(max_tokens=2000)
    messages: list[Any] = [
        SystemMessage(content=debrief_system_prompt(problem)),
        HumanMessage(content=f"Transcript:\n\n{transcript}"),
    ]
    resp = await llm.ainvoke(messages)
    raw = _flatten_llm_content(resp.content).strip()
    # Strip accidental code fences the model sometimes adds.
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

    parsed = _extract_first_json_object(raw)
    if parsed is None:
        log.warning("interview.debrief_parse_failed", raw=raw[:400])
        raise HTTPException(status_code=502, detail="Debrief scoring failed — try again")

    # Clean up the session now — the debrief is the artifact the user keeps.
    await store.delete(session_id)

    try:
        return DebriefResponse(**parsed)
    except Exception as exc:
        log.warning("interview.debrief_shape_mismatch", error=str(exc), parsed=parsed)
        raise HTTPException(status_code=502, detail="Debrief shape unexpected") from exc


@router.delete("/{session_id}", status_code=204)
async def abandon(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    store = await _store()
    session = await store.get(session_id)
    if session is None or session.user_id != str(current_user.id):
        return
    await store.delete(session_id)
