"""SRS routes (P2-05) — due-card list and review endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.srs import SRSCardResponse, SRSReviewRequest, SRSUpsertRequest
from app.services.srs_service import SRSService

router = APIRouter(prefix="/srs", tags=["srs"])


@router.get("/due", response_model=list[SRSCardResponse])
async def list_due_cards(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SRSCardResponse]:
    cards = await SRSService(db).list_due(user_id=current_user.id, limit=limit)
    return [SRSCardResponse.model_validate(c) for c in cards]


@router.post("/cards", response_model=SRSCardResponse, status_code=201)
async def create_card(
    payload: SRSUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SRSCardResponse:
    card = await SRSService(db).upsert_card(
        user_id=current_user.id,
        concept_key=payload.concept_key,
        prompt=payload.prompt,
    )
    return SRSCardResponse.model_validate(card)


@router.post("/cards/{card_id}/review", response_model=SRSCardResponse)
async def review_card(
    card_id: uuid.UUID,
    payload: SRSReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SRSCardResponse:
    try:
        card = await SRSService(db).review(
            user_id=current_user.id,
            card_id=card_id,
            quality=payload.quality,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="card not found")
    return SRSCardResponse.model_validate(card)
