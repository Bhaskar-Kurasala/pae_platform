"""Pydantic schemas for the feedback widget endpoints (#177)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class FeedbackCreate(BaseModel):
    route: str
    body: str
    sentiment: str | None = None
    url: str | None = None
    user_agent: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    app_version: str | None = None
    category: str | None = "other"
    severity: str | None = None
    error_id: str | None = None
    recent_route_history: list[str] | None = None


class FeedbackItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    route: str
    body: str
    sentiment: str | None
    resolved: bool
    created_at: datetime
    url: str | None = None
    user_agent: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    app_version: str | None = None
    category: str | None = None
    severity: str | None = None
    error_id: str | None = None
    recent_route_history: list[str] | None = None

    model_config = {"from_attributes": True}
