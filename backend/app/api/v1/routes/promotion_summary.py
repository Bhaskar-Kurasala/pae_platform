"""Promotion screen aggregator routes — read summary, confirm promotion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.promotion_summary import (
    PromotionConfirmResponse,
    PromotionSummaryResponse,
)
from app.services.promotion_summary_service import (
    build_promotion_summary,
    confirm_promotion,
)

router = APIRouter(prefix="/promotion", tags=["promotion"])


@router.get("/summary", response_model=PromotionSummaryResponse)
async def get_promotion_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromotionSummaryResponse:
    return await build_promotion_summary(db, user=current_user)


@router.post(
    "/confirm",
    response_model=PromotionConfirmResponse,
    status_code=status.HTTP_200_OK,
)
async def post_promotion_confirm(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromotionConfirmResponse:
    """Promote the student. 409 if the gate is not yet open.

    Idempotent — a second call returns the already-recorded timestamp.
    """
    result = await confirm_promotion(db, user=current_user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Promotion gate is not open yet.",
        )
    return result
