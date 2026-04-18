import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Mood = Literal["blocked", "meh", "steady", "flowing"]
# P3 3A-12: `day_end` is the only value used today — but the column is a
# string and future kinds will layer in without a schema change.
ReflectionKind = Literal["day_end"]


class ReflectionBase(BaseModel):
    mood: Mood
    note: str = Field(default="", max_length=280)


class ReflectionCreate(ReflectionBase):
    """Payload for POST /reflections/me — date defaults to today (UTC)."""

    reflection_date: date | None = None
    kind: ReflectionKind = "day_end"


class ReflectionResponse(ReflectionBase):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    reflection_date: date
    kind: ReflectionKind = "day_end"
    created_at: datetime
    updated_at: datetime
