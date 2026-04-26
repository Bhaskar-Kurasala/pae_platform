"""MockSessionOrchestrator — the v3 mock interview lifecycle.

Composes four sub-agents (QuestionSelector / Interviewer / Scorer / Analyst),
the rubric engine, pattern detector, and memory service. Holds the cost-cap
circuit breaker and writes per-turn cost logs.

Flow:

  start_session
    ├── load profile evidence + open weaknesses (MemoryService)
    ├── QuestionSelector → first question (warmup)
    ├── persist InterviewSession + MockQuestion
    └── return greeting + first question

  submit_answer
    ├── persist MockAnswer with pattern signals
    ├── Scorer → per-answer evaluation (with confidence)
    ├── Interviewer → reaction / probe / move_on
    ├── if Interviewer wants to probe → return follow-up question (no new MockQuestion row;
    │     the orchestrator stays on the same MockQuestion until move_on)
    ├── if move_on → QuestionSelector with rolling overall → next MockQuestion row
    ├── cost-cap check after each LLM call
    └── return evaluation + next_question + interviewer_reaction + cost

  complete_session
    ├── PatternDetector aggregate
    ├── Analyst → post-mortem
    ├── persist MockSessionReport
    ├── MemoryService.record_weakness_signals + mark_addressed
    └── return SessionReportResponse
"""

from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_factory import estimate_cost_inr, model_for
from app.models.agent_invocation_log import (
    SOURCE_MOCK,
    STATUS_SUCCEEDED,
)
from app.services.agent_invocation_logger import log_invocation
from app.agents.mock_sub_agents import (
    MockAnalyst,
    MockInterviewer,
    MockQuestionSelector,
    MockScorer,
    _usage_from,
)
from app.models.interview_session import InterviewSession
from app.models.mock_interview import (
    MockAnswer,
    MockCostLog,
    MockQuestion,
    MockSessionReport,
)
from app.services.career_service import (
    get_exercise_count,
    get_student_skill_map,
)
from app.services.mock_memory_service import (
    get_open_weaknesses,
    get_recent_reports,
    mark_addressed,
    memory_recall_greeting,
    record_weakness_signals,
)
from app.services.mock_pattern_detector import (
    AnswerSignals,
    aggregate_session_patterns,
    detect_answer_signals,
)
from app.services.mock_rubric_engine import rubric_for, warmup_rubric_hint

log = structlog.get_logger()

COST_CAP_INR = 40.0
CONFIDENCE_THRESHOLD = 0.6
MAX_PROBES_PER_QUESTION = 2


class CostCapExceededError(Exception):
    """Raised when accumulated cost exceeds the per-session ₹40 cap."""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StartResult:
    session: InterviewSession
    first_question: MockQuestion
    memory_recall: str | None


@dataclass
class AnswerResult:
    answer: MockAnswer
    evaluation: dict[str, Any]
    next_question: MockQuestion | None
    interviewer_reaction: str | None
    cost_inr_so_far: float
    cost_cap_exceeded: bool


@dataclass
class CompleteResult:
    session: InterviewSession
    report: MockSessionReport
    transcript: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Cost recording
# ---------------------------------------------------------------------------


async def _log_cost(
    db: AsyncSession,
    *,
    session: InterviewSession,
    sub_agent: str,
    response: Any,
    latency_ms: int,
    tier: str,
) -> float:
    """Record per-turn cost; return INR delta for this call.

    Dual-writes to agent_invocation_log during the migration window
    (sunset 2026-05-09). MockCostLog remains the authoritative read source
    until the parallel-read gate flips.
    """
    in_tok, out_tok = _usage_from(response)
    model = model_for(tier)  # type: ignore[arg-type]
    delta = estimate_cost_inr(model=model, input_tokens=in_tok, output_tokens=out_tok)
    db.add(
        MockCostLog(
            session_id=session.id,
            sub_agent=sub_agent,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_inr=delta,
            latency_ms=latency_ms,
        )
    )
    await log_invocation(
        db,
        user_id=session.user_id,
        source=SOURCE_MOCK,
        source_id=session.id,
        sub_agent=sub_agent,
        model=model,
        tokens_in=in_tok,
        tokens_out=out_tok,
        cost_inr=delta,
        latency_ms=latency_ms,
        status=STATUS_SUCCEEDED,
    )
    session.total_cost_inr = round((session.total_cost_inr or 0.0) + delta, 4)
    await db.flush()
    return delta


def _check_cost_cap(session: InterviewSession) -> None:
    if (session.total_cost_inr or 0.0) > COST_CAP_INR:
        raise CostCapExceededError(
            f"Mock interview cost cap exceeded: ₹{session.total_cost_inr:.2f} > ₹{COST_CAP_INR}"
        )


# ---------------------------------------------------------------------------
# Profile evidence loader
# ---------------------------------------------------------------------------


async def _build_evidence(
    db: AsyncSession, *, user_id: uuid.UUID
) -> dict[str, Any]:
    """Compact JSON the QuestionSelector + Analyst are allowed to cite from."""
    skill_map = await get_student_skill_map(db, user_id=user_id)
    exercise_count = await get_exercise_count(db, user_id=user_id)
    return {
        "skills": [
            {"name": k, "confidence": round(v, 2)}
            for k, v in sorted(skill_map.items(), key=lambda x: x[1], reverse=True)[:20]
        ],
        "exercise_count": exercise_count,
    }


def _weakness_dicts(weaknesses: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "concept": w.concept,
            "severity": round(w.severity, 2),
            "last_seen_at": w.last_seen_at.isoformat() if w.last_seen_at else None,
        }
        for w in weaknesses
    ]


# ---------------------------------------------------------------------------
# Rolling overall calculator
# ---------------------------------------------------------------------------


async def _rolling_overall(
    db: AsyncSession, *, session_id: uuid.UUID
) -> float | None:
    """Average overall score across already-evaluated answers in this session."""
    result = await db.execute(
        select(MockAnswer.evaluation).where(MockAnswer.session_id == session_id)
    )
    rows = [r[0] for r in result.all() if r[0]]
    overalls = [
        float(r.get("overall", 0.0))
        for r in rows
        if isinstance(r, dict) and r.get("overall") is not None
    ]
    if not overalls:
        return None
    return round(sum(overalls) / len(overalls), 2)


async def _prior_question_texts(
    db: AsyncSession, *, session_id: uuid.UUID
) -> list[str]:
    result = await db.execute(
        select(MockQuestion.text)
        .where(MockQuestion.session_id == session_id)
        .order_by(MockQuestion.position.asc())
    )
    return [r[0] for r in result.all()]


async def _current_open_question(
    db: AsyncSession, *, session_id: uuid.UUID
) -> MockQuestion | None:
    """The latest MockQuestion that doesn't yet have a completed answer scored
    with `move_on`. Used so probes attach to the correct question row."""
    result = await db.execute(
        select(MockQuestion)
        .where(MockQuestion.session_id == session_id)
        .order_by(MockQuestion.position.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _probe_count(
    db: AsyncSession, *, question_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(MockAnswer).where(MockAnswer.question_id == question_id)
    )
    return len(list(result.scalars().all()))


# ---------------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------------


async def start_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    mode: str,
    target_role: str,
    level: str,
    jd_text: str | None,
    voice_enabled: bool,
) -> StartResult:
    if mode == "system_design":
        # Phase 2 stub — explicitly refused at the orchestrator, never reaches Sonnet.
        raise ValueError("system_design mode is Phase 2 — not yet available.")

    session = InterviewSession(
        user_id=user_id,
        mode=mode,
        status="active",
        target_role=target_role,
        level=level,
        jd_text=jd_text,
        voice_enabled=voice_enabled,
        questions_asked=[],
        scores=[],
        total_cost_inr=0.0,
    )
    db.add(session)
    await db.flush()

    evidence = await _build_evidence(db, user_id=user_id)
    weaknesses = await get_open_weaknesses(db, user_id=user_id)

    selector = MockQuestionSelector()
    started_at = time.monotonic()
    parsed, response = await selector.invoke(
        mode=mode,
        target_role=target_role,
        level=level,
        jd_text=jd_text,
        evidence=evidence,
        weakness_ledger=_weakness_dicts(weaknesses),
        rolling_overall=None,
        prior_questions=[],
        is_warmup=True,
    )
    latency_ms = int((time.monotonic() - started_at) * 1000)
    await _log_cost(
        db,
        session=session,
        sub_agent=selector.sub_agent_name,
        response=response,
        latency_ms=latency_ms,
        tier=selector.tier,
    )

    q_payload = parsed.get("question", {}) if isinstance(parsed, dict) else {}
    q_text = (q_payload.get("text") or "").strip()
    if not q_text:
        raise RuntimeError("QuestionSelector returned no question text.")

    question = MockQuestion(
        session_id=session.id,
        text=q_text,
        mode=mode,
        difficulty=float(q_payload.get("difficulty", 0.2)),
        source=str(q_payload.get("source", "generated")),
        rubric={
            "hint": q_payload.get("rubric_hint", warmup_rubric_hint(mode)),  # type: ignore[arg-type]
            "criteria": rubric_for(mode, level),  # type: ignore[arg-type]
            "references_weakness": q_payload.get("references_weakness"),
        },
        position=1,
    )
    db.add(question)
    await db.commit()
    await db.refresh(session)
    await db.refresh(question)

    greeting = memory_recall_greeting(weaknesses)

    log.info(
        "mock.session_started",
        session_id=str(session.id),
        mode=mode,
        target_role=target_role,
        level=level,
        voice_enabled=voice_enabled,
    )
    return StartResult(session=session, first_question=question, memory_recall=greeting)


# ---------------------------------------------------------------------------
# submit_answer
# ---------------------------------------------------------------------------


async def submit_answer(
    db: AsyncSession,
    *,
    session: InterviewSession,
    question_id: uuid.UUID,
    text: str,
    audio_ref: str | None,
    latency_ms: int | None,
    time_to_first_word_ms: int | None,
) -> AnswerResult:
    """Score the answer, run the Interviewer, and decide the next question."""
    q_result = await db.execute(
        select(MockQuestion).where(
            MockQuestion.id == question_id,
            MockQuestion.session_id == session.id,
        )
    )
    question = q_result.scalar_one_or_none()
    if question is None:
        raise ValueError("Question does not belong to session.")

    signals = detect_answer_signals(text)

    # ── Score the answer ───────────────────────────────────────────
    rubric = (question.rubric or {}).get("criteria") or rubric_for(
        question.mode, session.level or "junior"  # type: ignore[arg-type]
    )

    prior_reports = await get_recent_reports(db, user_id=session.user_id, limit=3)
    prior_context = _summarize_prior_reports(prior_reports)

    scorer = MockScorer()
    started = time.monotonic()
    eval_parsed, eval_response = await scorer.invoke(
        mode=question.mode,
        level=session.level or "junior",
        question=question.text,
        answer=text,
        rubric=rubric,
        prior_session_context=prior_context,
    )
    eval_latency = int((time.monotonic() - started) * 1000)
    await _log_cost(
        db,
        session=session,
        sub_agent=scorer.sub_agent_name,
        response=eval_response,
        latency_ms=eval_latency,
        tier=scorer.tier,
    )

    # Honor confidence threshold — if Scorer confidence is low, mark for human review.
    confidence = float(eval_parsed.get("confidence", 0.0))
    needs_human_review = bool(eval_parsed.get("needs_human_review")) or (
        confidence < CONFIDENCE_THRESHOLD
    )
    eval_parsed["needs_human_review"] = needs_human_review
    if needs_human_review and not eval_parsed.get("feedback", "").startswith(
        "I'd recommend a human review"
    ):
        eval_parsed["feedback"] = (
            "I'd recommend a human review on this one. "
            + eval_parsed.get("feedback", "")
        )

    # ── Persist answer ─────────────────────────────────────────────
    answer = MockAnswer(
        question_id=question.id,
        session_id=session.id,
        text=text,
        audio_ref=audio_ref,
        evaluation=eval_parsed,
        confidence=confidence,
        latency_ms=latency_ms,
        filler_word_count=signals.filler_word_count,
        time_to_first_word_ms=time_to_first_word_ms,
        word_count=signals.word_count,
    )
    db.add(answer)
    await db.flush()

    # Record weakness signals from this answer
    weakness_signals = eval_parsed.get("weakness_signals") or []
    if isinstance(weakness_signals, list):
        await record_weakness_signals(
            db,
            user_id=session.user_id,
            session_id=session.id,
            signals=[s for s in weakness_signals if isinstance(s, dict)],
        )

    # ── Interviewer reaction ───────────────────────────────────────
    transcript_for_interviewer = await _transcript_for_interviewer(db, session=session)
    probe_count = await _probe_count(db, question_id=question.id)

    interviewer = MockInterviewer()
    started = time.monotonic()
    react_parsed, react_response = await interviewer.invoke(
        mode=question.mode,
        voice_enabled=session.voice_enabled,
        question=question.text,
        rubric_hint=(question.rubric or {}).get("hint", ""),
        candidate_answer=text,
        transcript=transcript_for_interviewer,
        probe_count_on_question=probe_count,
    )
    react_latency = int((time.monotonic() - started) * 1000)
    await _log_cost(
        db,
        session=session,
        sub_agent=interviewer.sub_agent_name,
        response=react_response,
        latency_ms=react_latency,
        tier=interviewer.tier,
    )

    next_action = react_parsed.get("next_action", "move_on")
    interviewer_reaction = react_parsed.get("reply", "")

    # Force move-on if we've already probed the max.
    if next_action == "probe" and probe_count >= MAX_PROBES_PER_QUESTION:
        next_action = "move_on"

    # ── Cost-cap check before deciding next question ───────────────
    cost_cap_hit = (session.total_cost_inr or 0.0) > COST_CAP_INR

    next_question: MockQuestion | None = None
    if cost_cap_hit:
        # Don't burn more LLM money picking a next question; orchestrator returns
        # the eval + reaction and the route closes the session.
        log.warning(
            "mock.cost_cap_hit",
            session_id=str(session.id),
            cost=session.total_cost_inr,
        )
    elif next_action == "move_on":
        # Pick the next question via QuestionSelector.
        rolling = await _rolling_overall(db, session_id=session.id)
        prior_questions = await _prior_question_texts(db, session_id=session.id)

        evidence = await _build_evidence(db, user_id=session.user_id)
        weaknesses = await get_open_weaknesses(db, user_id=session.user_id)

        selector = MockQuestionSelector()
        started = time.monotonic()
        try:
            next_parsed, next_response = await selector.invoke(
                mode=question.mode,
                target_role=session.target_role or "Software Engineer",
                level=session.level or "junior",
                jd_text=session.jd_text,
                evidence=evidence,
                weakness_ledger=_weakness_dicts(weaknesses),
                rolling_overall=rolling,
                prior_questions=prior_questions,
                is_warmup=False,
            )
            sel_latency = int((time.monotonic() - started) * 1000)
            await _log_cost(
                db,
                session=session,
                sub_agent=selector.sub_agent_name,
                response=next_response,
                latency_ms=sel_latency,
                tier=selector.tier,
            )

            q_payload = next_parsed.get("question", {}) if isinstance(next_parsed, dict) else {}
            q_text = (q_payload.get("text") or "").strip()
            if q_text:
                next_question = MockQuestion(
                    session_id=session.id,
                    text=q_text,
                    mode=question.mode,
                    difficulty=float(q_payload.get("difficulty", 0.5)),
                    source=str(q_payload.get("source", "generated")),
                    rubric={
                        "hint": q_payload.get("rubric_hint", ""),
                        "criteria": rubric_for(
                            question.mode,  # type: ignore[arg-type]
                            session.level or "junior",  # type: ignore[arg-type]
                        ),
                        "references_weakness": q_payload.get("references_weakness"),
                    },
                    position=len(prior_questions) + 1,
                )
                db.add(next_question)
        except CostCapExceededError:
            cost_cap_hit = True
        except Exception as exc:
            log.warning("mock.next_question_failed", error=str(exc))
    # else: next_action == "probe" — stay on same question; no next_question

    await db.commit()
    if next_question is not None:
        await db.refresh(next_question)
    await db.refresh(answer)

    return AnswerResult(
        answer=answer,
        evaluation=eval_parsed,
        next_question=next_question,
        interviewer_reaction=interviewer_reaction or None,
        cost_inr_so_far=round(session.total_cost_inr or 0.0, 4),
        cost_cap_exceeded=cost_cap_hit,
    )


# ---------------------------------------------------------------------------
# complete_session
# ---------------------------------------------------------------------------


async def complete_session(
    db: AsyncSession,
    *,
    session: InterviewSession,
) -> CompleteResult:
    transcript = await _build_transcript(db, session=session)

    answer_signals = []
    ttfw_samples: list[int] = []
    answers_meta: list[dict[str, Any]] = []
    result = await db.execute(
        select(MockAnswer).where(MockAnswer.session_id == session.id)
    )
    for ans in result.scalars().all():
        answer_signals.append(
            AnswerSignals(
                word_count=ans.word_count,
                filler_word_count=ans.filler_word_count,
                hedge_word_count=0,  # already folded into confidence_language
                evasion_hits=0,
            )
        )
        if ans.time_to_first_word_ms is not None:
            ttfw_samples.append(ans.time_to_first_word_ms)
        answers_meta.append(
            {
                "answer_id": str(ans.id),
                "evaluation": ans.evaluation,
                "confidence": ans.confidence,
                "filler_word_count": ans.filler_word_count,
                "word_count": ans.word_count,
            }
        )

    patterns = aggregate_session_patterns(
        answer_signals=answer_signals,
        time_to_first_word_samples=ttfw_samples,
    )

    prior_reports = await get_recent_reports(db, user_id=session.user_id, limit=3)
    weaknesses = await get_open_weaknesses(db, user_id=session.user_id)

    analyst = MockAnalyst()
    started = time.monotonic()
    parsed, response = await analyst.invoke(
        session_meta={
            "mode": session.mode,
            "target_role": session.target_role,
            "level": session.level,
            "voice_enabled": session.voice_enabled,
            "total_cost_inr": session.total_cost_inr,
        },
        transcript=transcript,
        evaluations=[a["evaluation"] for a in answers_meta if a.get("evaluation")],
        patterns=patterns.to_dict(),
        prior_reports=[
            {
                "headline": r.headline,
                "verdict": r.verdict,
                "rubric_summary": r.rubric_summary,
                "weaknesses": r.weaknesses,
                "next_action": r.next_action,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in prior_reports
        ],
        weakness_ledger=_weakness_dicts(weaknesses),
    )
    analyst_latency = int((time.monotonic() - started) * 1000)
    await _log_cost(
        db,
        session=session,
        sub_agent=analyst.sub_agent_name,
        response=response,
        latency_ms=analyst_latency,
        tier=analyst.tier,
    )

    analyst_confidence = float(parsed.get("analyst_confidence", 0.5))
    needs_review = bool(parsed.get("needs_human_review")) or (
        analyst_confidence < CONFIDENCE_THRESHOLD
    )

    # ── Persist report ─────────────────────────────────────────────
    report = MockSessionReport(
        session_id=session.id,
        rubric_summary=parsed.get("rubric_summary") or {},
        patterns=patterns.to_dict(),
        strengths=parsed.get("strengths") or [],
        weaknesses=parsed.get("weaknesses") or [],
        next_action=parsed.get("next_action"),
        headline=parsed.get("headline"),
        verdict="needs_human_review" if needs_review else parsed.get("verdict"),
        analyst_confidence=analyst_confidence,
    )
    db.add(report)

    # ── Compute overall_score from evaluations ─────────────────────
    overalls: list[float] = []
    for a in answers_meta:
        ev = a.get("evaluation") or {}
        if isinstance(ev, dict) and ev.get("overall") is not None:
            try:
                overalls.append(float(ev["overall"]))
            except (TypeError, ValueError):
                continue
    if overalls:
        session.overall_score = round(sum(overalls) / len(overalls), 2)

    session.status = "completed"

    # ── Address weaknesses that scored well this session ───────────
    addressed_concepts: list[str] = []
    for update in parsed.get("weakness_ledger_updates") or []:
        if isinstance(update, dict) and update.get("addressed"):
            addressed_concepts.append(str(update.get("concept", "")))
    if addressed_concepts:
        await mark_addressed(
            db, user_id=session.user_id, concepts=addressed_concepts
        )

    await db.commit()
    await db.refresh(session)
    await db.refresh(report)

    log.info(
        "mock.session_completed",
        session_id=str(session.id),
        overall=session.overall_score,
        cost_inr=session.total_cost_inr,
        analyst_confidence=analyst_confidence,
        needs_human_review=needs_review,
    )

    return CompleteResult(session=session, report=report, transcript=transcript)


# ---------------------------------------------------------------------------
# Share token
# ---------------------------------------------------------------------------


async def issue_share_token(
    db: AsyncSession, *, session: InterviewSession
) -> str:
    if session.share_token:
        return session.share_token
    token = secrets.token_urlsafe(24)
    session.share_token = token
    await db.commit()
    return token


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


async def _build_transcript(
    db: AsyncSession, *, session: InterviewSession
) -> list[dict[str, Any]]:
    """Question + answer turns interleaved, ordered."""
    q_result = await db.execute(
        select(MockQuestion)
        .where(MockQuestion.session_id == session.id)
        .order_by(MockQuestion.position.asc())
    )
    questions = list(q_result.scalars().all())

    a_result = await db.execute(
        select(MockAnswer)
        .where(MockAnswer.session_id == session.id)
        .order_by(MockAnswer.created_at.asc())
    )
    answers = list(a_result.scalars().all())
    answers_by_qid: dict[uuid.UUID, list[MockAnswer]] = {}
    for a in answers:
        answers_by_qid.setdefault(a.question_id, []).append(a)

    transcript: list[dict[str, Any]] = []
    for q in questions:
        transcript.append(
            {
                "role": "interviewer",
                "text": q.text,
                "at": q.created_at,
                "audio_ref": None,
                "question_id": str(q.id),
            }
        )
        for a in answers_by_qid.get(q.id, []):
            transcript.append(
                {
                    "role": "candidate",
                    "text": a.text,
                    "at": a.created_at,
                    "audio_ref": a.audio_ref,
                    "answer_id": str(a.id),
                    "evaluation": a.evaluation,
                }
            )
    return transcript


async def _transcript_for_interviewer(
    db: AsyncSession, *, session: InterviewSession
) -> list[dict[str, str]]:
    """Compact transcript for the Interviewer's context window."""
    transcript = await _build_transcript(db, session=session)
    return [
        {"role": t["role"], "text": t["text"]}
        for t in transcript
    ]


def _summarize_prior_reports(reports: list[MockSessionReport]) -> str:
    if not reports:
        return ""
    lines: list[str] = []
    for r in reports[:3]:
        if r.headline:
            lines.append(f"- {r.headline}")
        if r.weaknesses:
            for w in (r.weaknesses or [])[:2]:
                lines.append(f"  · {w}")
    return "\n".join(lines)
