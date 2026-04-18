"""User preferences service — upsert/get for the single row per user."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preferences import TUTOR_MODES, UserPreferences


class PreferencesService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(self, user_id: uuid.UUID) -> UserPreferences:
        prefs = (
            await self.db.execute(
                select(UserPreferences).where(UserPreferences.user_id == user_id)
            )
        ).scalar_one_or_none()
        if prefs is not None:
            return prefs
        prefs = UserPreferences(user_id=user_id)
        self.db.add(prefs)
        await self.db.commit()
        await self.db.refresh(prefs)
        return prefs

    async def update(
        self,
        user_id: uuid.UUID,
        *,
        tutor_mode: str | None = None,
        ugly_draft_mode: bool | None = None,
    ) -> UserPreferences:
        prefs = await self.get_or_create(user_id)
        if tutor_mode is not None:
            if tutor_mode not in TUTOR_MODES:
                raise ValueError(f"unknown tutor_mode: {tutor_mode}")
            prefs.tutor_mode = tutor_mode
        if ugly_draft_mode is not None:
            prefs.ugly_draft_mode = ugly_draft_mode
        await self.db.commit()
        await self.db.refresh(prefs)
        return prefs
