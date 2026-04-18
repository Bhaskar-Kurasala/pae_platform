"""Pydantic schemas for saved skill path (#24)."""

import uuid

from pydantic import BaseModel


class SavedPathRequest(BaseModel):
    skill_ids: list[uuid.UUID]


class SavedPathResponse(BaseModel):
    user_id: uuid.UUID
    skill_ids: list[uuid.UUID]
