"""Daily intention schemas (P3 3A-11)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyIntentionCreate(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class DailyIntentionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    intention_date: date
    text: str
    created_at: datetime
    updated_at: datetime
