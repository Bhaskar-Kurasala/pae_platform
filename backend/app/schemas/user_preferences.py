from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

TutorMode = Literal["standard", "socratic_strict"]


class UserPreferencesResponse(BaseModel):
    model_config = {"from_attributes": True}

    tutor_mode: TutorMode
    ugly_draft_mode: bool


class UserPreferencesUpdate(BaseModel):
    tutor_mode: TutorMode | None = None
    ugly_draft_mode: bool | None = None
