from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WeeklyIntentionCreate(BaseModel):
    items: list[str] = Field(max_length=3)


class WeeklyIntentionItem(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    week_starting: date
    slot: int
    text: str
    created_at: datetime


class WeeklyIntentionsResponse(BaseModel):
    week_starting: date
    items: list[WeeklyIntentionItem]
