"""Today screen API (P3 3A-11 and following).

Thin route surface for the student's "Today" workspace — intention
prompt first, with sibling tickets adding micro-wins, end-of-day
reflection, and stuck-intervention banners over time.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.daily_intention import (
    DailyIntentionCreate,
    DailyIntentionResponse,
)
from app.services.daily_intention_service import (
    get_for_date,
    today_in_utc,
    upsert_today,
)

router = APIRouter(prefix="/today", tags=["today"])


@router.post("/intention", response_model=DailyIntentionResponse)
async def set_today_intention(
    payload: DailyIntentionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyIntentionResponse:
    """Set or overwrite today's intention for the current user."""
    row = await upsert_today(db, user_id=current_user.id, text=payload.text)
    return DailyIntentionResponse.model_validate(row)


@router.get("/intention", response_model=DailyIntentionResponse | None)
async def get_today_intention(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyIntentionResponse | None:
    """Return today's intention for the current user, or null if unset."""
    row = await get_for_date(
        db, user_id=current_user.id, on=today_in_utc()
    )
    return DailyIntentionResponse.model_validate(row) if row else None
