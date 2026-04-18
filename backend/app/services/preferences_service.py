"""User preferences service — upsert/get for the single row per user."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preferences import TUTOR_MODES, UserPreferences

log = structlog.get_logger()


# Level labels used in UI copy and telemetry. Keep aligned with the frontend
# SocraticSlider; drift between the two would make telemetry hard to read.
SOCRATIC_LEVEL_LABELS: dict[int, str] = {
    0: "off",
    1: "gentle",
    2: "standard",
    3: "strict",
}


def tutor_mode_for_level(level: int) -> str:
    """Keep `tutor_mode` in sync with the numeric level.

    Level 3 still toggles the legacy `socratic_strict` overlay so existing
    prompt rules keep firing. Levels 0-2 all map to `standard`; the graded
    behavior comes from the prompt overlay, not from a different mode string.
    """
    return "socratic_strict" if level >= 3 else "standard"


def level_from_tutor_mode(mode: str) -> int:
    """Inverse — used for rows written before 3A-3 that only had tutor_mode."""
    return 3 if mode == "socratic_strict" else 0


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
        socratic_level: int | None = None,
        ugly_draft_mode: bool | None = None,
    ) -> UserPreferences:
        """Partial update. Level and mode stay in sync — passing either one
        updates both so callers can't end up in a mismatched state where
        mode says strict but level is 0 (or vice-versa).
        """
        prefs = await self.get_or_create(user_id)
        previous_level = prefs.socratic_level

        if socratic_level is not None:
            if not 0 <= socratic_level <= 3:
                raise ValueError(f"socratic_level out of range: {socratic_level}")
            prefs.socratic_level = socratic_level
            prefs.tutor_mode = tutor_mode_for_level(socratic_level)
        elif tutor_mode is not None:
            if tutor_mode not in TUTOR_MODES:
                raise ValueError(f"unknown tutor_mode: {tutor_mode}")
            prefs.tutor_mode = tutor_mode
            # Only snap the numeric level when the legacy toggle is flipped
            # explicitly — otherwise a standalone tutor_mode="standard" write
            # from an old client would clobber a deliberate level=1 or 2.
            if tutor_mode == "socratic_strict":
                prefs.socratic_level = 3
            elif previous_level == 3:
                prefs.socratic_level = 0

        if ugly_draft_mode is not None:
            prefs.ugly_draft_mode = ugly_draft_mode

        await self.db.commit()
        await self.db.refresh(prefs)

        if socratic_level is not None and socratic_level != previous_level:
            log.info(
                "preference.socratic_level_changed",
                user_id=str(user_id),
                **{"from": previous_level, "to": socratic_level},
            )
        return prefs
