"""Mock Interview v3 API.

Routes:
  POST   /mock/sessions/start                     — start a session, get the first question
  POST   /mock/sessions/{session_id}/answer       — submit an answer; get eval + next question
  POST   /mock/sessions/{session_id}/complete     — finish, get the post-mortem report
  GET    /mock/sessions/{session_id}/report       — fetch a session's report (auth required)
  GET    /mock/sessions                           — list my sessions
  POST   /mock/sessions/{session_id}/share        — issue a share token
  GET    /mock/public-reports/{share_token}       — read-only shared report (no auth)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.interview_session import InterviewSession
from app.models.mock_interview import MockSessionReport
from app.models.user import User
from app.schemas.mock_interview import (
    AnswerEvaluation,
    CompleteSessionResponse,
    MockQuestionPayload,
    MockSessionListItem,
    MockTranscriptTurn,
    NextAction,
    PatternInsights,
    RubricCriterion,
    SessionReportResponse,
    ShareResponse,
    StartMockRequest,
    StartMockResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.services.mock_interview_service import (
    CostCapExceededError,
    complete_session,
    issue_share_token,
    start_session,
    submit_answer,
    _build_transcript,
)

log = structlog.get_logger()

router = APIRouter(prefix="/mock", tags=["mock-interview"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> InterviewSession:
    result = await db.execute(
        select(InterviewSession).where(InterviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _evaluation_payload(eval_dict: dict[str, Any]) -> AnswerEvaluation:
    """Translate a Scorer JSON into the public-facing AnswerEvaluation schema.

    When `needs_human_review` is true, the client must hide numeric scores —
    we still send them but the API marks the flag clearly.
    """
    criteria_raw = eval_dict.get("criteria") or []
    criteria = []
    for c in criteria_raw:
        if not isinstance(c, dict):
            continue
        try:
            criteria.append(
                RubricCriterion(
                    name=str(c.get("name", "")),
                    score=int(c.get("score", 0)),
                    rationale=str(c.get("rationale", "")),
                )
            )
        except (TypeError, ValueError):
            continue
    return AnswerEvaluation(
        criteria=criteria,
        overall=float(eval_dict.get("overall", 0.0)),
        confidence=float(eval_dict.get("confidence", 0.0)),
        would_pass=bool(eval_dict.get("would_pass", False)),
        feedback=str(eval_dict.get("feedback", "")),
        needs_human_review=bool(eval_dict.get("needs_human_review", False)),
    )


def _question_payload(question: Any) -> MockQuestionPayload:
    return MockQuestionPayload(
        id=question.id,
        text=question.text,
        mode=question.mode,
        difficulty=float(question.difficulty),
        source=question.source,
        position=int(question.position),
    )


async def _build_report_response(
    db: AsyncSession,
    *,
    session: InterviewSession,
    report: MockSessionReport,
) -> SessionReportResponse:
    transcript_raw = await _build_transcript(db, session=session)
    transcript = [
        MockTranscriptTurn(
            role=t["role"],
            text=t["text"],
            at=t["at"],
            audio_ref=t.get("audio_ref"),
        )
        for t in transcript_raw
    ]

    p = report.patterns or {}
    patterns = PatternInsights(
        filler_word_rate=float(p.get("filler_word_rate", 0.0)),
        avg_time_to_first_word_ms=p.get("avg_time_to_first_word_ms"),
        avg_words_per_answer=float(p.get("avg_words_per_answer", 0.0)),
        evasion_count=int(p.get("evasion_count", 0)),
        confidence_language_score=float(p.get("confidence_language_score", 5.0)),
    )

    next_action_raw = report.next_action or {}
    next_action = NextAction(
        label=str(next_action_raw.get("label", "Review the transcript")),
        detail=str(next_action_raw.get("detail", "")),
        target_url=next_action_raw.get("target_url"),
    )

    return SessionReportResponse(
        session_id=session.id,
        headline=str(report.headline or ""),
        verdict=str(report.verdict or "needs_human_review"),
        rubric_summary={k: float(v) for k, v in (report.rubric_summary or {}).items()},
        patterns=patterns,
        strengths=list(report.strengths or []),
        weaknesses=list(report.weaknesses or []),
        next_action=next_action,
        analyst_confidence=float(report.analyst_confidence or 0.0),
        needs_human_review=(report.verdict == "needs_human_review")
        or (float(report.analyst_confidence or 0.0) < 0.6),
        transcript=transcript,
        total_cost_inr=round(session.total_cost_inr or 0.0, 4),
        share_token=session.share_token,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/sessions/start", response_model=StartMockResponse, status_code=201)
@limiter.limit("10/minute")
async def start_mock_session(
    request: Request,
    payload: StartMockRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StartMockResponse:
    try:
        result = await start_session(
            db,
            user_id=current_user.id,
            mode=payload.mode,
            target_role=payload.target_role,
            level=payload.level,
            jd_text=payload.jd_text,
            voice_enabled=payload.voice_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("mock.start.failed", error=str(exc))
        raise HTTPException(
            status_code=500, detail="Failed to start mock session."
        ) from exc

    return StartMockResponse(
        session_id=result.session.id,
        mode=result.session.mode,  # type: ignore[arg-type]
        target_role=result.session.target_role or payload.target_role,
        level=result.session.level or payload.level,  # type: ignore[arg-type]
        voice_enabled=result.session.voice_enabled,
        first_question=_question_payload(result.first_question),
        memory_recall=result.memory_recall,
    )


@router.post(
    "/sessions/{session_id}/answer",
    response_model=SubmitAnswerResponse,
)
@limiter.limit("30/minute")
async def submit_mock_answer(
    request: Request,
    session_id: uuid.UUID,
    payload: SubmitAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmitAnswerResponse:
    session = await _load_session(db, session_id=session_id, user_id=current_user.id)
    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed.")

    try:
        result = await submit_answer(
            db,
            session=session,
            question_id=payload.question_id,
            text=payload.text,
            audio_ref=payload.audio_ref,
            latency_ms=payload.latency_ms,
            time_to_first_word_ms=payload.time_to_first_word_ms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CostCapExceededError as exc:
        log.warning(
            "mock.answer.cost_cap",
            session_id=str(session.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=402,
            detail="Mock interview cost cap reached. End the session to view your report.",
        ) from exc
    except Exception as exc:
        log.exception("mock.answer.failed", error=str(exc))
        raise HTTPException(
            status_code=500, detail="Failed to evaluate answer."
        ) from exc

    return SubmitAnswerResponse(
        answer_id=result.answer.id,
        evaluation=_evaluation_payload(result.evaluation),
        next_question=(
            _question_payload(result.next_question) if result.next_question else None
        ),
        interviewer_reaction=result.interviewer_reaction,
        cost_inr_so_far=result.cost_inr_so_far,
        cost_cap_exceeded=result.cost_cap_exceeded,
    )


@router.post(
    "/sessions/{session_id}/complete",
    response_model=CompleteSessionResponse,
)
async def complete_mock_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompleteSessionResponse:
    session = await _load_session(db, session_id=session_id, user_id=current_user.id)
    if session.status == "completed":
        # Idempotent — return the existing report
        existing = await db.execute(
            select(MockSessionReport).where(MockSessionReport.session_id == session.id)
        )
        report = existing.scalar_one_or_none()
        if report is None:
            raise HTTPException(
                status_code=409, detail="Session is completed but report is missing."
            )
        body = await _build_report_response(db, session=session, report=report)
        return CompleteSessionResponse(
            session_id=session.id, status=session.status, report=body
        )

    try:
        result = await complete_session(db, session=session)
    except Exception as exc:
        log.exception("mock.complete.failed", error=str(exc))
        raise HTTPException(
            status_code=500, detail="Failed to generate session report."
        ) from exc

    body = await _build_report_response(db, session=result.session, report=result.report)
    return CompleteSessionResponse(
        session_id=result.session.id,
        status=result.session.status,
        report=body,
    )


@router.get(
    "/sessions/{session_id}/report",
    response_model=SessionReportResponse,
)
async def get_mock_report(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionReportResponse:
    session = await _load_session(db, session_id=session_id, user_id=current_user.id)
    result = await db.execute(
        select(MockSessionReport).where(MockSessionReport.session_id == session.id)
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not yet generated. Complete the session first.",
        )
    return await _build_report_response(db, session=session, report=report)


@router.get(
    "/sessions",
    response_model=list[MockSessionListItem],
)
async def list_my_mock_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MockSessionListItem]:
    result = await db.execute(
        select(InterviewSession)
        .where(InterviewSession.user_id == current_user.id)
        .where(InterviewSession.target_role.isnot(None))  # mock v3 sessions only
        .order_by(InterviewSession.created_at.desc())
        .limit(20)
    )
    sessions = list(result.scalars().all())
    return [
        MockSessionListItem(
            id=s.id,
            mode=s.mode,
            target_role=s.target_role,
            status=s.status,
            overall_score=s.overall_score,
            total_cost_inr=round(s.total_cost_inr or 0.0, 4),
            created_at=s.created_at,
        )
        for s in sessions
    ]


@router.post(
    "/sessions/{session_id}/share",
    response_model=ShareResponse,
)
async def share_mock_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShareResponse:
    session = await _load_session(db, session_id=session_id, user_id=current_user.id)
    if session.status != "completed":
        raise HTTPException(
            status_code=400, detail="Only completed sessions can be shared."
        )
    token = await issue_share_token(db, session=session)
    return ShareResponse(
        share_token=token,
        public_url=f"/mock-report/{token}",
    )


@router.get(
    "/public-reports/{share_token}",
    response_model=SessionReportResponse,
)
async def get_public_mock_report(
    share_token: str,
    db: AsyncSession = Depends(get_db),
) -> SessionReportResponse:
    """Read-only public report — no auth required. Only completed sessions
    with a share_token are surfaced."""
    result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.share_token == share_token,
            InterviewSession.status == "completed",
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    rep_result = await db.execute(
        select(MockSessionReport).where(MockSessionReport.session_id == session.id)
    )
    report = rep_result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return await _build_report_response(db, session=session, report=report)
