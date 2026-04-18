"""Schema for weekly growth snapshots / receipts (P1-C-2, P1-C-3, P3B)."""

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
