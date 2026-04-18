"""Schema for weekly growth snapshots / receipts (P1-C-2, P1-C-3).

Adds `SkillGapEntry` (P3 3A-16) for the Receipts gap-analysis card.
"""

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


class SkillGapEntry(BaseModel):
    """One gap entry on the Receipts page (P3 3A-16)."""

    skill_id: uuid.UUID
    skill_slug: str
    skill_name: str
    mastery: float
    last_touched_at: datetime | None
    days_since_touched: int
    # Pre-rendered phrase like "3 weeks ago" / "never touched" so the
    # frontend doesn't duplicate the formatting rules.
    last_touched_label: str
