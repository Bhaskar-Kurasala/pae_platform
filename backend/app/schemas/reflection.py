import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Mood = Literal["blocked", "meh", "steady", "flowing"]


class ReflectionBase(BaseModel):
    mood: Mood
    note: str = Field(default="", max_length=280)


class ReflectionCreate(ReflectionBase):
    """Payload for POST /reflections/me — date defaults to today (UTC)."""

    reflection_date: date | None = None


class ReflectionResponse(ReflectionBase):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    reflection_date: date
    created_at: datetime
    updated_at: datetime
