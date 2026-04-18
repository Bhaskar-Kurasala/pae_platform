from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.diagnostic import (
    DiagnosticQuestion,
    DiagnosticQuestionsResponse,
    DiagnosticScaleItem,
    DiagnosticSubmission,
    DiagnosticSubmitResponse,
)
from app.services.diagnostic_service import DiagnosticService, get_questions

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


@router.post("/submit", response_model=DiagnosticSubmitResponse)
async def submit_diagnostic(
    payload: DiagnosticSubmission,
    service: DiagnosticService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> DiagnosticSubmitResponse:
    updated = await service.submit(current_user, payload)
    return DiagnosticSubmitResponse(states_updated=updated)
