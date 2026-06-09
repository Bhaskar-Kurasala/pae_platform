"""Path screen aggregator schemas.

The Path UI renders three things from this single payload:
  1. A 6-star constellation (current → goal role).
  2. A Level 1 ladder with the active course's lessons + their labs.
  3. A proof wall — top peer-shared submissions.

All numbers come from real signals (skills graph + user_skill_states + saved
path + course progress + exercise rows). The aggregator is read-only.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

StarState = Literal["done", "current", "upcoming", "goal"]
LessonStatus = Literal["done", "current", "upcoming"]
LabStatus = Literal["done", "current", "locked"]


class PathStar(BaseModel):
    """Single star in the constellation. `label` may include a single line break
    encoded as `\n` (UI splits on that). `sub` is one short qualifier like
    "Mastered" / "In progress" / "58 days" / "Destination"."""

    label: str
    sub: str
    state: StarState
    badge: str  # "1".."5" for ordered roles, "★" for goal


class PathLab(BaseModel):
    """One exercise attached to a lesson. The Path screen treats these as
    bite-sized hands-on builds beneath the active lesson."""

    id: uuid.UUID
    title: str
    description: str | None
    duration_minutes: int
    status: LabStatus  # done / current / locked


class PathLesson(BaseModel):
    id: uuid.UUID
    title: str
    meta: str  # "Required · today · 3 labs · tap to expand"
    duration_minutes: int
    status: LessonStatus
    labs: list[PathLab]
    labs_completed: int  # for the "1 of 3 complete" header


class PathLevel(BaseModel):
    """One rung in the ladder — typically the student's currently-active
    course (Level 1) and the next-track up-sell (Level 2)."""

    badge: str  # "1", "2", "★"
    title: str  # course or role title
    blurb: str
    progress_percentage: int
    lessons: list[PathLesson]
    state: Literal["current", "upcoming", "goal"]
    # Optional unlock CTA for the next-track rung.
    unlock_course_id: uuid.UUID | None = None
    unlock_price_cents: int | None = None
    unlock_currency: str | None = None
    unlock_lesson_count: int | None = None
    unlock_lab_count: int | None = None


class PathProofEntry(BaseModel):
    """One peer-shared submission that students can read for inspiration."""

    submission_id: uuid.UUID
    code_snippet: str
    author_name: str
    score: int
    promoted: bool


class PathSummaryResponse(BaseModel):
    overall_progress: int  # 0..100
    active_course_id: uuid.UUID | None
    active_course_title: str | None
    constellation: list[PathStar]  # 6 stars (5 roles + 1 goal)
    levels: list[PathLevel]  # current + next + goal (3 rungs)
    proof_wall: list[PathProofEntry]  # 0..2 entries
