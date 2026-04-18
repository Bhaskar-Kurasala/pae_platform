"""Confidence calibration endpoint (P3 3A-7).

Lets the student submit a 1-5 self-report. The frontend invokes this when
the student answers the tutor's "how confident?" prompt. Kept isolated
from the streaming endpoint so one student abandoning the prompt doesn't
leave a half-written row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.confidence import ConfidenceReportCreate, ConfidenceReportResponse
from app.services.confidence_service import record_report

router = APIRouter(prefix="/confidence", tags=["confidence"])


@router.post("/reports", response_model=ConfidenceReportResponse, status_code=201)
async def create_confidence_report(
    payload: ConfidenceReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConfidenceReportResponse:
    row = await record_report(
        db,
        user_id=current_user.id,
        value=payload.value,
        skill_id=payload.skill_id,
        asked_at=payload.asked_at,
    )
    await db.commit()
    await db.refresh(row)
    return ConfidenceReportResponse.model_validate(row)
