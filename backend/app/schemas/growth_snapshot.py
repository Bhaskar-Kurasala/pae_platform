"""Schema for weekly growth snapshots / receipts (P1-C-2, P1-C-3, P3B).

Adds `SkillGapEntry` (P3 3A-16) for the Receipts gap-analysis card.
P3B adds enriched weekly receipt schemas (WeekReceiptResponse and sub-schemas).
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

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


# ---------------------------------------------------------------------------
# P3B enriched receipt schemas
# ---------------------------------------------------------------------------


class WowData(BaseModel):
    lessons_delta: int | None
    lessons_trend: Literal["up", "down", "flat", "first_week"]


class SkillCoverageItem(BaseModel):
    id: str
    name: str
    mastery: float


class PortfolioItem(BaseModel):
    id: str
    exercise_title: str
    submitted_at: str


class ReflectionSummary(BaseModel):
    mood_counts: dict[str, int]
    dominant_mood: str


class DayActivity(BaseModel):
    day: str
    minutes: int


class NextWeekSuggestion(BaseModel):
    skill_name: str
    current_mastery: float


class WeekReceiptResponse(BaseModel):
    week_over_week: WowData
    skills_touched_detail: list[SkillCoverageItem]
    portfolio_items: list[PortfolioItem]
    reflection_summary: ReflectionSummary
    daily_activity: list[DayActivity]
    next_week_suggestion: NextWeekSuggestion | None
