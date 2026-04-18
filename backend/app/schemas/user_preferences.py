from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TutorMode = Literal["standard", "socratic_strict"]


class UserPreferencesResponse(BaseModel):
    model_config = {"from_attributes": True}

    tutor_mode: TutorMode
    socratic_level: int
    ugly_draft_mode: bool


class UserPreferencesUpdate(BaseModel):
    # tutor_mode remains for clients that still toggle strict directly.
    # New clients should write socratic_level; service keeps the two in sync.
    tutor_mode: TutorMode | None = None
    socratic_level: int | None = Field(default=None, ge=0, le=3)
    ugly_draft_mode: bool | None = None
