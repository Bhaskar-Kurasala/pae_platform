"""D12 / Pass 3c E4 — study_planner output schema.

Three modes share one schema. Mode field disambiguates which sub-set of
fields is populated per call.

Singular `handoff_request` (not plural) per E4 spec — study_planner
hands off to career_coach when strategic re-plan is needed.
handoff_request is NEVER populated in D12 (Option B).

Output-text projection: top-level `answer` field stamped by run() via
_compose_answer_text per docs/followups/output-text-projection-convention.md.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.supervisor import HandoffRequest


class DailyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_of_week: Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    duration_minutes: int = Field(ge=0, le=480)
    focus_area: str = Field(max_length=120)
    specific_target: str = Field(max_length=200)


class SessionActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_minutes: int = Field(ge=5, le=300)
    activity_type: Literal[
        "new_lesson", "practice", "review", "capstone_work",
        "interview_prep", "rest"
    ]
    specific_target: str = Field(max_length=200)
    why_now: str = Field(max_length=200)


class StudyPlannerOutput(BaseModel):
    """Pass 3c E4 verbatim. Three modes, shared schema.

    Field-population rules:
      • mode="weekly_plan"     → week_starting, total_hours_planned, daily_blocks
      • mode="session_plan"    → session_date, session_duration_minutes, activities,
                                  success_criteria
      • mode="adherence_check" → adherence_score, summary, suggested_adjustment

    handoff_request: singular, NEVER populated in D12 (Option B).
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["weekly_plan", "session_plan", "adherence_check"]

    # weekly_plan fields
    week_starting: date | None = None
    total_hours_planned: float | None = Field(default=None, ge=0.0, le=168.0)
    daily_blocks: list[DailyBlock] = Field(default_factory=list)

    # session_plan fields
    session_date: date | None = None
    session_duration_minutes: int | None = Field(default=None, ge=5, le=480)
    activities: list[SessionActivity] = Field(default_factory=list)
    success_criteria: str | None = Field(default=None, max_length=300)

    # adherence_check fields
    adherence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    summary: str | None = None
    suggested_adjustment: str | None = Field(default=None, max_length=400)

    handoff_request: HandoffRequest | None = Field(
        default=None,
        description=(
            "D12 (Option B): NEVER populated by the prompt. "
            "Strategic re-plan signals surface as text in summary. "
            "D13 may flip this."
        ),
    )


__all__ = [
    "DailyBlock",
    "SessionActivity",
    "StudyPlannerOutput",
]
