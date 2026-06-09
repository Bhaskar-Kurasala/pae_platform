import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deprecated import deprecated
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.diagnostic import (
    DiagnosticCTARequest,
    DiagnosticCTAResponse,
    DiagnosticQuestion,
    DiagnosticQuestionsResponse,
    DiagnosticScaleItem,
    DiagnosticSubmission,
    DiagnosticSubmitResponse,
)
from app.services.diagnostic_cta_service import record_cta_decision
from app.services.diagnostic_service import DiagnosticService, get_questions

log = structlog.get_logger()

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


def get_service(db: AsyncSession = Depends(get_db)) -> DiagnosticService:
    return DiagnosticService(db)


@router.get("/questions", response_model=DiagnosticQuestionsResponse)
async def list_questions() -> DiagnosticQuestionsResponse:
    bank = get_questions()
    return DiagnosticQuestionsResponse(
        questions=[DiagnosticQuestion(**q) for q in bank["questions"]],
        scale=[DiagnosticScaleItem(**s) for s in bank["scale"]],
    )


@router.post("/cta-decision", response_model=DiagnosticCTAResponse)
@deprecated(sunset="2026-07-01", reason="diagnostic legacy -- superseded by readiness events")
async def record_diagnostic_cta(
    payload: DiagnosticCTARequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DiagnosticCTAResponse:
    """Record the student's decision on the diagnostic opt-in CTA (P3 3B #4)."""
    await record_cta_decision(
        db,
        user_id=current_user.id,
        decision=payload.decision,
        note=payload.note,
    )
    log.info(
        "onboarding.diagnostic_cta_decision",
        user_id=str(current_user.id),
        decision=payload.decision,
    )
    return DiagnosticCTAResponse(decision=payload.decision, recorded=True)


@router.post("/submit", response_model=DiagnosticSubmitResponse)
async def submit_diagnostic(
    payload: DiagnosticSubmission,
    service: DiagnosticService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> DiagnosticSubmitResponse:
    updated = await service.submit(current_user, payload)
    return DiagnosticSubmitResponse(states_updated=updated)
