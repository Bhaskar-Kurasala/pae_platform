"""Interview Prep service v2 — live mock interview sessions, rubric scoring, story bank CRUD.

Design decisions:
  - Sessions are persisted to PostgreSQL (interview_sessions table) so users can
    review past performance.  The ephemeral Redis-backed sessions in interview_service.py
    remain untouched; this service is additive.
  - evaluate_answer uses claude-haiku-4-5-20251001 (called per answer — cost-sensitive).
  - get_opening_question uses claude-sonnet-4-6 (quality matters; called once per session).
  - JSON extraction uses the same balanced-brace regex helper pattern used in the
    existing interview route to be resilient to LLM prose wrapping.
"""

from __future__ import annotations

import json
import re
import uuid
from statistics import mean
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_factory import build_llm
from app.models.interview_session import InterviewSession
from app.models.story_bank import StoryBank
from app.schemas.interview import AnswerEvaluation, RubricScores

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# JSON helpers (mirrors pattern in app/api/v1/routes/interview.py)
# ---------------------------------------------------------------------------


def _flatten_content(content: Any) -> str:
    """Flatten Anthropic list-of-dicts content; skip thinking blocks."""
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


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the first balanced {...} JSON object in *text*, or None."""
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


def _strip_code_fence(text: str) -> str:
    """Remove leading/trailing markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Opening question generation
# ---------------------------------------------------------------------------

_OPENING_SYSTEM = {
    "behavioral": (
        "You are a senior interviewer at a top tech company. "
        "Generate ONE behavioral interview question that asks about a specific past experience. "
        "Use the STAR format cue (Situation, Task, Action, Result). "
        "Be concrete and specific — avoid generic 'tell me about a time' with no context. "
        "Return only the question, no preamble."
    ),
    "technical": (
        "You are a senior software engineer conducting a technical interview. "
        "Generate ONE technical question that tests conceptual understanding or problem-solving. "
        "If a topic is provided, make the question specific to that topic. "
        "Return only the question, no preamble."
    ),
    "system_design": (
        "You are a staff engineer conducting a system design interview. "
        "Generate ONE system design question that requires designing a realistic production system. "
        "Make it specific — name the product or domain. Return only the question, no preamble."
    ),
}


async def get_opening_question(mode: str, topic: str | None) -> str:
    """Generate a contextual opening interview question via claude-sonnet-4-6."""
    system_prompt = _OPENING_SYSTEM.get(mode, _OPENING_SYSTEM["technical"])
    user_content = (
        f"Generate a {mode} interview question"
        + (f" focused on: {topic}" if topic else "")
        + "."
    )

    try:
        llm = build_llm(max_tokens=300)
        result = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])
        question: str = (result.content if isinstance(result.content, str) else "").strip()
    except Exception as exc:
        log.warning("interview_v2.llm_unavailable_using_fallback", error=str(exc))
        question = ""

    if not question:
        # Fallback so the session can still start
        question = _fallback_question(mode, topic)

    log.info("interview_v2.opening_question_generated", mode=mode, topic=topic)
    return question


def _fallback_question(mode: str, topic: str | None) -> str:
    fallbacks = {
        "behavioral": (
            "Tell me about a time you had to make a high-stakes technical decision "
            "under a tight deadline. What was the situation, and what did you do?"
        ),
        "technical": (
            f"Explain how {topic or 'a REST API'} works and describe a production "
            "edge case you would need to handle."
        ),
        "system_design": (
            "Design a URL-shortening service that can handle 100 million URLs. "
            "Walk me through your architecture."
        ),
    }
    return fallbacks.get(mode, fallbacks["technical"])


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def start_interview_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    mode: str,
    topic: str | None,
) -> tuple[InterviewSession, str]:
    """Create a new interview session and generate the opening question.

    Returns:
        (InterviewSession, first_question_text)
    """
    first_question = await get_opening_question(mode, topic)

    session = InterviewSession(
        user_id=user_id,
        mode=mode,
        status="active",
        questions_asked=[first_question],
        scores=[],
        overall_score=None,
    )
    db.add(session)
    await db.flush()  # get the auto-generated id without committing
    await db.commit()
    await db.refresh(session)

    log.info(
        "interview_v2.session_started",
        session_id=str(session.id),
        user_id=str(user_id),
        mode=mode,
    )
    return session, first_question


# ---------------------------------------------------------------------------
# Answer evaluation (claude-haiku-4-5-20251001 — cost-sensitive)
# ---------------------------------------------------------------------------

_RUBRIC_SYSTEM = """\
You are an expert interview coach evaluating a candidate's answer to an interview question.

Score the answer on FIVE dimensions (0-10 each):
  - clarity: How clear and easy to follow is the answer?
  - structure: Does the answer have a logical structure (e.g. STAR for behavioral, problem→solution→trade-offs for technical)?
  - depth: Does the answer show genuine expertise and detail?
  - evidence: Are claims backed by concrete examples, metrics, or specifics?
  - confidence_language: Does the candidate speak confidently without excessive hedging?

Return a JSON object with EXACTLY this schema — no prose, no code fences:
{
  "scores": {
    "clarity": <int 0-10>,
    "structure": <int 0-10>,
    "depth": <int 0-10>,
    "evidence": <int 0-10>,
    "confidence_language": <int 0-10>
  },
  "overall": <float 0-10, mean of the five scores>,
  "feedback": "<2-4 sentences of specific, actionable feedback>",
  "next_question": "<follow-up question to probe depth or a new question if the topic is exhausted>",
  "tip": "<one concrete improvement tip for the candidate>"
}
"""


async def evaluate_answer(
    db: AsyncSession,
    session_id: uuid.UUID,
    question: str,
    answer: str,
    mode: str,
) -> AnswerEvaluation:
    """Call claude-haiku-4-5-20251001 to score the answer on 5 rubric dimensions.

    Updates session.questions_asked and session.scores in the DB.
    """
    user_content = (
        f"Interview mode: {mode}\n\n"
        f"Question: {question}\n\n"
        f"Candidate's answer:\n{answer}"
    )

    raw_text = ""
    try:
        llm = build_llm(max_tokens=800)
        result = await llm.ainvoke([
            SystemMessage(content=_RUBRIC_SYSTEM),
            HumanMessage(content=user_content),
        ])
        raw_text = result.content if isinstance(result.content, str) else ""
    except Exception as exc:
        log.warning("interview_v2.rubric_llm_unavailable", error=str(exc))

    raw_text = _strip_code_fence(raw_text)

    parsed = _extract_json_object(raw_text)
    if parsed is None:
        log.warning(
            "interview_v2.rubric_parse_failed",
            session_id=str(session_id),
            raw=raw_text[:400],
        )
        # Return a safe default so the session doesn't die
        parsed = {
            "scores": {
                "clarity": 5,
                "structure": 5,
                "depth": 5,
                "evidence": 5,
                "confidence_language": 5,
            },
            "overall": 5.0,
            "feedback": "Unable to parse evaluation — please try again.",
            "next_question": "Can you elaborate on that answer with a concrete example?",
            "tip": "Add specific examples with measurable outcomes.",
        }

    # Build typed evaluation
    scores_raw = parsed.get("scores", {})
    rubric = RubricScores(
        clarity=int(scores_raw.get("clarity", 5)),
        structure=int(scores_raw.get("structure", 5)),
        depth=int(scores_raw.get("depth", 5)),
        evidence=int(scores_raw.get("evidence", 5)),
        confidence_language=int(scores_raw.get("confidence_language", 5)),
    )
    overall_score = float(parsed.get("overall", mean([
        rubric.clarity, rubric.structure, rubric.depth,
        rubric.evidence, rubric.confidence_language,
    ])))
    evaluation = AnswerEvaluation(
        scores=rubric,
        overall=overall_score,
        feedback=str(parsed.get("feedback", "")),
        next_question=str(parsed.get("next_question", "")),
        tip=str(parsed.get("tip", "")),
    )

    # Persist to DB: append question + score to session
    result = await db.execute(
        select(InterviewSession).where(InterviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is not None:
        # Append the follow-up question so the client always knows what's next
        questions = list(session.questions_asked or [])
        if evaluation.next_question and evaluation.next_question not in questions:
            questions.append(evaluation.next_question)

        score_entry = {
            "question": question,
            "overall": overall_score,
            "scores": {
                "clarity": rubric.clarity,
                "structure": rubric.structure,
                "depth": rubric.depth,
                "evidence": rubric.evidence,
                "confidence_language": rubric.confidence_language,
            },
        }
        scores = list(session.scores or [])
        scores.append(score_entry)

        session.questions_asked = questions
        session.scores = scores
        await db.commit()

        log.info(
            "interview_v2.answer_evaluated",
            session_id=str(session_id),
            overall=overall_score,
        )

    return evaluation


# ---------------------------------------------------------------------------
# Complete session
# ---------------------------------------------------------------------------


async def complete_session(db: AsyncSession, session_id: uuid.UUID) -> InterviewSession:
    """Mark session complete and compute overall_score = mean of all answer overalls."""
    result = await db.execute(
        select(InterviewSession).where(InterviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found")

    scores = list(session.scores or [])
    if scores:
        answer_overalls = [s.get("overall", 0.0) for s in scores if isinstance(s, dict)]
        session.overall_score = round(mean(answer_overalls), 2) if answer_overalls else None
    else:
        session.overall_score = None

    session.status = "completed"
    await db.commit()
    await db.refresh(session)

    log.info(
        "interview_v2.session_completed",
        session_id=str(session_id),
        overall_score=session.overall_score,
        answers_count=len(scores),
    )
    return session


# ---------------------------------------------------------------------------
# Story bank CRUD
# ---------------------------------------------------------------------------


async def create_story(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    situation: str,
    task: str,
    action: str,
    result: str,
    tags: list[str],
) -> StoryBank:
    """Create a new STAR story entry for a user."""
    story = StoryBank(
        user_id=user_id,
        title=title,
        situation=situation,
        task=task,
        action=action,
        result=result,
        tags=tags,
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    log.info("interview_v2.story_created", story_id=str(story.id), user_id=str(user_id))
    return story


async def get_stories(db: AsyncSession, user_id: uuid.UUID) -> list[StoryBank]:
    """Return all STAR stories for a user, newest first."""
    result = await db.execute(
        select(StoryBank)
        .where(StoryBank.user_id == user_id)
        .order_by(StoryBank.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_story(db: AsyncSession, user_id: uuid.UUID, story_id: uuid.UUID) -> bool:
    """Delete a story belonging to the user. Returns True if deleted, False if not found."""
    result = await db.execute(
        select(StoryBank).where(StoryBank.id == story_id, StoryBank.user_id == user_id)
    )
    story = result.scalar_one_or_none()
    if story is None:
        return False
    await db.delete(story)
    await db.commit()
    log.info("interview_v2.story_deleted", story_id=str(story_id), user_id=str(user_id))
    return True


async def list_sessions(db: AsyncSession, user_id: uuid.UUID, limit: int = 10) -> list[InterviewSession]:
    """Return the most recent sessions for a user."""
    result = await db.execute(
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
