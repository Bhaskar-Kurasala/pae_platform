"""Schema for weekly growth snapshots / receipts (P1-C-2, P1-C-3)."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class GrowthSnapshotResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    week_ending: date
    lessons_completed: int
    skills_touched: int
    streak_days: int
    top_concept: str | None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
