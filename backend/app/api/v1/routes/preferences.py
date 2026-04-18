"""User preferences routes — tutor_mode, ugly_draft_mode."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.user_preferences import (
    UserPreferencesResponse,
    UserPreferencesUpdate,
)
from app.services.preferences_service import PreferencesService

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("/me", response_model=UserPreferencesResponse)
async def get_my_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    prefs = await PreferencesService(db).get_or_create(current_user.id)
    return UserPreferencesResponse.model_validate(prefs)


@router.patch("/me", response_model=UserPreferencesResponse)
async def update_my_preferences(
    payload: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    prefs = await PreferencesService(db).update(
        current_user.id,
        tutor_mode=payload.tutor_mode,
        ugly_draft_mode=payload.ugly_draft_mode,
    )
    return UserPreferencesResponse.model_validate(prefs)
