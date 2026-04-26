"""Today screen aggregator schemas (DISC: today refactor 2026-04-26).

One round-trip for the Today UI. Decoupling from the per-feature endpoints
lets the Today screen stay fast even when individual sources grow.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TodayUser(BaseModel):
    first_name: str = ""


class TodayGoal(BaseModel):
    success_statement: str | None = None
    target_role: str | None = None
    days_remaining: int = 0
    motivation: str | None = None


class TodayConsistency(BaseModel):
    days_active: int = Field(ge=0)
    window_days: int = Field(ge=1)


class TodayProgress(BaseModel):
    overall_percentage: float = 0.0
    lessons_completed_total: int = 0
    lessons_total: int = 0
    today_unlock_percentage: float = 0.0
    active_course_id: uuid.UUID | None = None
    active_course_title: str | None = None
    next_lesson_id: uuid.UUID | None = None
    next_lesson_title: str | None = None


class TodaySession(BaseModel):
    id: uuid.UUID | None = None
    ordinal: int = 1
    started_at: datetime | None = None
    warmup_done_at: datetime | None = None
    lesson_done_at: datetime | None = None
    reflect_done_at: datetime | None = None


class TodayCurrentFocus(BaseModel):
    skill_slug: str | None = None
    skill_name: str | None = None
    skill_blurb: str | None = None


class TodayCapstone(BaseModel):
    exercise_id: uuid.UUID | None = None
    title: str | None = None
    days_to_due: int | None = None
    draft_quality: int | None = None
    drafts_count: int = 0


class TodayMilestone(BaseModel):
    label: str | None = None
    days: int = 0


class TodayReadiness(BaseModel):
    current: int = 0
    delta_week: int = 0


class TodayIntention(BaseModel):
    text: str | None = None


class TodayMicroWin(BaseModel):
    kind: str
    label: str
    occurred_at: datetime


class TodayCohortEvent(BaseModel):
    kind: str
    actor_handle: str
    label: str
    occurred_at: datetime


class TodaySummaryResponse(BaseModel):
    user: TodayUser
    goal: TodayGoal
    consistency: TodayConsistency
    progress: TodayProgress
    session: TodaySession
    current_focus: TodayCurrentFocus
    capstone: TodayCapstone
    next_milestone: TodayMilestone
    readiness: TodayReadiness
    intention: TodayIntention
    due_card_count: int = 0
    peers_at_level: int = 0
    promotions_today: int = 0
    micro_wins: list[TodayMicroWin] = []
    cohort_events: list[TodayCohortEvent] = []
