"""Interview simulation endpoints (P2-10) + Interview Prep v2 (sessions, rubric, story bank).

Thin controller around InterviewSessionStore + the interviewer system prompt.
Streaming shares the SSE format used elsewhere in the app so the frontend can
reuse its token-reader.

v2 endpoints added below the existing routes (prefix /interview/sessions and
/interview/stories) are backed by the PostgreSQL-persisted InterviewSession and
StoryBank models via interview_service_v2.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_factory import build_llm
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.interview import (
    AnswerEvaluation,
    AnswerSubmitRequest,
    SessionListItem,
    SessionResponse,
    StartSessionRequest,
    StoryBankCreateRequest,
    StoryBankItem,
)
from app.services.interview_service import (
    INTERVIEWER_SYSTEM_PROMPT,
    InterviewSessionStore,
    PROBLEM_BANK,
    debrief_system_prompt,
    pick_problem,
)
from app.services.interview_service_v2 import (
    complete_session,
    create_story,
    delete_story,
    evaluate_answer,
    get_stories,
    list_sessions,
    start_interview_session,
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


# ===========================================================================
# Interview Prep v2 — persisted sessions, rubric scoring, story bank
# ===========================================================================


@router.post("/sessions/start", response_model=SessionResponse, status_code=201)
async def start_session(
    payload: StartSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Start a new mock interview session and receive the opening question."""
    session, first_question = await start_interview_session(
        db,
        user_id=current_user.id,
        mode=payload.mode,
        topic=payload.topic,
    )
    return SessionResponse(
        id=session.id,
        mode=session.mode,
        status=session.status,
        first_question=first_question,
        overall_score=session.overall_score,
    )


@router.post("/sessions/answer", response_model=AnswerEvaluation)
async def submit_answer(
    payload: AnswerSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnswerEvaluation:
    """Submit an answer to a question; receive rubric scores and the next question."""
    from sqlalchemy import select as sa_select

    from app.models.interview_session import InterviewSession as _IS

    # Verify session ownership before evaluating
    result = await db.execute(sa_select(_IS).where(_IS.id == payload.session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj is None or session_obj.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session_obj.status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed")

    return await evaluate_answer(
        db,
        session_id=payload.session_id,
        question=payload.question,
        answer=payload.answer,
        mode=session_obj.mode,
    )


@router.post("/sessions/{session_id}/complete")
async def complete_interview_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark a session as completed and compute the overall score."""
    from sqlalchemy import select as sa_select

    from app.models.interview_session import InterviewSession as _IS

    result = await db.execute(sa_select(_IS).where(_IS.id == session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj is None or session_obj.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    completed = await complete_session(db, session_id=session_id)
    return {
        "id": str(completed.id),
        "status": completed.status,
        "overall_score": completed.overall_score,
        "answers_count": len(completed.scores or []),
    }


@router.get("/sessions", response_model=list[SessionListItem])
async def list_interview_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionListItem]:
    """Return the last 10 sessions for the authenticated user."""
    sessions = await list_sessions(db, user_id=current_user.id, limit=10)
    return [
        SessionListItem(
            id=s.id,
            mode=s.mode,
            status=s.status,
            overall_score=s.overall_score,
            questions_count=len(s.questions_asked or []),
        )
        for s in sessions
    ]


# ---------------------------------------------------------------------------
# Story bank CRUD
# ---------------------------------------------------------------------------


@router.post("/stories", response_model=StoryBankItem, status_code=201)
async def create_story_entry(
    payload: StoryBankCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryBankItem:
    """Save a new STAR story to the story bank."""
    story = await create_story(
        db,
        user_id=current_user.id,
        title=payload.title,
        situation=payload.situation,
        task=payload.task,
        action=payload.action,
        result=payload.result,
        tags=payload.tags,
    )
    return StoryBankItem(
        id=story.id,
        title=story.title,
        situation=story.situation,
        task=story.task,
        action=story.action,
        result=story.result,
        tags=story.tags or [],
    )


@router.get("/stories", response_model=list[StoryBankItem])
async def list_stories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StoryBankItem]:
    """Return all STAR stories for the authenticated user."""
    stories = await get_stories(db, user_id=current_user.id)
    return [
        StoryBankItem(
            id=s.id,
            title=s.title,
            situation=s.situation,
            task=s.task,
            action=s.action,
            result=s.result,
            tags=s.tags or [],
        )
        for s in stories
    ]


@router.delete("/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story_entry(
    story_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a story from the story bank."""
    deleted = await delete_story(db, user_id=current_user.id, story_id=story_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Story not found")
