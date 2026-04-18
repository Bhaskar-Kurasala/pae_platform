"""Pydantic schemas for the feedback widget endpoints (#177)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class FeedbackCreate(BaseModel):
    route: str
    body: str
    sentiment: str | None = None


class FeedbackItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    route: str
    body: str
    sentiment: str | None
    resolved: bool
    created_at: datetime

    model_config = {"from_attributes": True}
