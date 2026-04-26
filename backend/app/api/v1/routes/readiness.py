"""Readiness diagnostic API.

Routes:
  POST /api/v1/readiness/diagnostic/sessions               — start a session
  POST /api/v1/readiness/diagnostic/sessions/{id}/turn     — submit a turn
  POST /api/v1/readiness/diagnostic/sessions/{id}/finalize — finalize → verdict (commit 7)
  POST /api/v1/readiness/diagnostic/sessions/{id}/abandon  — mark abandoned
  GET  /api/v1/readiness/diagnostic/sessions               — list past diagnoses
  POST /api/v1/readiness/diagnostic/next-action/click      — north-star beacon (commit 10)
"""

from __future__ import annotations

import uuid
from typing import cast

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.readiness import (
    CompletionCheckResponse,
    EvidenceChip,
    FinalizeRequest,
    FinalizeResponse,
    NextAction,
    NextActionClickResponse,
    NextActionIntent,
    NorthStarRateResponse,
    PastDiagnosesResponse,
    PastDiagnosis,
    StartDiagnosticResponse,
    TurnRequest,
    TurnResponse,
    VerdictPayload,
)
from app.schemas.readiness_overview import OverviewResponse, ProofResponse
from app.services.readiness_memory_service import list_past_diagnoses
from app.services.readiness_overview_service import load_overview
from app.services.readiness_proof_service import load_proof
from app.services.readiness_north_star import (
    SessionMissingVerdictError,
    check_completion,
    compute_north_star_rate,
    record_click,
)
from app.services.readiness_orchestrator import (
    CostCapExceededError,
    SessionAlreadyClosedError,
    SessionNotFoundError,
    abandon_session,
    finalize_session,
    start_session,
    submit_turn,
)

log = structlog.get_logger()

router = APIRouter(
    prefix="/readiness/diagnostic",
    tags=["readiness-diagnostic"],
)

# Separate router for the workspace aggregators — different prefix so we
# don't collide with the diagnostic conversation surface above.
overview_router = APIRouter(
    prefix="/readiness",
    tags=["readiness-overview"],
)


@overview_router.get("/overview", response_model=OverviewResponse)
async def get_readiness_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OverviewResponse:
    """One-shot payload for the Job Readiness Overview view."""
    return await load_overview(db, user=current_user)


@overview_router.get("/proof", response_model=ProofResponse)
async def get_readiness_proof(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProofResponse:
    """One-shot payload for the Proof Portfolio view."""
    return await load_proof(db, user=current_user)


def _require_flag() -> None:
    if not settings.feature_readiness_diagnostic:
        raise HTTPException(
            status_code=404,
            detail="Readiness diagnostic is not enabled in this environment.",
        )


@router.post("/sessions", response_model=StartDiagnosticResponse)
async def post_start_session(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StartDiagnosticResponse:
    _require_flag()
    try:
        result = await start_session(db, user_id=current_user.id)
    except CostCapExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Diagnostic cost cap reached.",
        ) from exc

    return StartDiagnosticResponse(
        session_id=result.session_id,
        opening_message=result.opening_message,
        snapshot_summary=result.snapshot_summary,
        prior_session_hint=result.prior_session_hint,
    )


@router.post(
    "/sessions/{session_id}/turn",
    response_model=TurnResponse,
)
async def post_turn(
    session_id: uuid.UUID,
    payload: TurnRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TurnResponse:
    _require_flag()
    try:
        result = await submit_turn(
            db,
            user_id=current_user.id,
            session_id=session_id,
            student_message=payload.content,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionAlreadyClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CostCapExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Diagnostic cost cap reached.",
        ) from exc

    return TurnResponse(
        session_id=result.session_id,
        turn=result.turn,
        agent_message=result.agent_message,
        is_final=result.is_final,
        invoke_jd_decoder=result.invoke_jd_decoder,
    )


@router.post(
    "/sessions/{session_id}/finalize",
    response_model=FinalizeResponse,
)
async def post_finalize_session(
    session_id: uuid.UUID,
    payload: FinalizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FinalizeResponse:
    _require_flag()
    try:
        result = await finalize_session(
            db,
            user_id=current_user.id,
            session_id=session_id,
            closing_note=payload.closing_note,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionAlreadyClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CostCapExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Diagnostic cost cap reached.",
        ) from exc

    v = result.verdict
    return FinalizeResponse(
        session_id=result.session_id,
        verdict=VerdictPayload(
            headline=v.headline,
            evidence=[
                EvidenceChip(
                    text=str(c.get("text", "")),
                    evidence_id=str(c.get("evidence_id", "")),
                    kind=c.get("kind", "neutral"),
                    source_url=c.get("source_url"),
                )
                for c in v.evidence
                if isinstance(c, dict) and c.get("evidence_id")
            ],
            next_action=NextAction(
                # Router validated the intent against the catalog already,
                # so the runtime value is always one of the Literal members.
                intent=cast(NextActionIntent, v.next_action_intent),
                route=v.next_action_route,
                label=v.next_action_label,
            ),
        ),
        sycophancy_flags=v.sycophancy_flags,
    )


@router.post("/sessions/{session_id}/abandon", status_code=204)
async def post_abandon_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _require_flag()
    try:
        await abandon_session(
            db, user_id=current_user.id, session_id=session_id
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionAlreadyClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sessions", response_model=PastDiagnosesResponse)
async def get_past_diagnoses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PastDiagnosesResponse:
    _require_flag()
    items = await list_past_diagnoses(db, user_id=current_user.id)
    return PastDiagnosesResponse(
        items=[PastDiagnosis(**item) for item in items]
    )


# ---------------------------------------------------------------------------
# North-star instrumentation (commit 10)
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/next-action/click",
    response_model=NextActionClickResponse,
)
async def post_next_action_click(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NextActionClickResponse:
    """Beacon called when the student clicks the verdict's primary CTA.

    Idempotent — a repeat click returns the original timestamp. The
    completion check runs separately when the student returns to the
    Job Readiness page.
    """
    _require_flag()
    try:
        clicked_at = await record_click(
            db, user_id=current_user.id, session_id=session_id
        )
    except SessionMissingVerdictError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NextActionClickResponse(
        session_id=session_id, clicked_at=clicked_at
    )


@router.post(
    "/sessions/{session_id}/check-completion",
    response_model=CompletionCheckResponse,
)
async def post_check_completion(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompletionCheckResponse:
    """Inspect activity since the click and stamp completion if the
    per-intent criterion is met. Idempotent. Frontend calls this on
    Job Readiness page load — students who acted on the verdict
    typically return to Job Readiness, which is the natural moment to
    stamp completion."""
    _require_flag()
    try:
        result = await check_completion(
            db, user_id=current_user.id, session_id=session_id
        )
    except SessionMissingVerdictError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CompletionCheckResponse(
        session_id=result.session_id,
        clicked_at=result.clicked_at,
        completed_at=result.completed_at,
        completed_within_window=result.completed_within_window,
        intent=cast(NextActionIntent | None, result.intent)
        if result.intent
        else None,
    )


@router.get("/north-star", response_model=NorthStarRateResponse)
async def get_north_star_rate(
    window_days: int = 14,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NorthStarRateResponse:
    """The page's north-star metric over a rolling window. Available
    to any authenticated user for now; tighten to admin-only when an
    admin layer ships for this surface."""
    _require_flag()
    if window_days < 1 or window_days > 90:
        raise HTTPException(
            status_code=400,
            detail="window_days must be between 1 and 90",
        )
    rate = await compute_north_star_rate(db, window_days=window_days)
    return NorthStarRateResponse(
        window_days=rate.window_days,
        sessions_with_verdict=rate.sessions_with_verdict,
        sessions_clicked=rate.sessions_clicked,
        sessions_completed_within_24h=rate.sessions_completed_within_24h,
        click_through_rate=rate.click_through_rate,
        completion_within_24h_rate=rate.completion_within_24h_rate,
    )
