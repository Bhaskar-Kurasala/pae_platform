"""D12 / Pass 3c E3 — career_coach output schema.

Plural `handoff_requests` (list, not singular) per spec line 696, 739.
handoff_requests is NEVER populated in D12 (Option B per
docs/followups/handoff-protocol-d11-d13.md).

market_signals field is intentionally ABSENT — read_market_signals is
deferred indefinitely per Deferral C (no curated source available; tracked
in Pass 3d §F.3). Graceful absence: no field, not an empty field.

Output-text projection: top-level `answer` field stamped by run() per
docs/followups/output-text-projection-convention.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.supervisor import HandoffRequest


class WeeklyFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week: int
    theme: str = Field(max_length=100)
    primary_activity: str = Field(max_length=200)
    secondary_activity: str | None = Field(default=None, max_length=200)


class ProjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=100)
    description: str = Field(max_length=300)
    priority: str = Field(max_length=40)


class CareerPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeline_weeks: int = Field(ge=1, le=104)
    weekly_focus_areas: list[WeeklyFocus] = Field(default_factory=list)
    projects_to_complete: list[ProjectRef] = Field(default_factory=list)
    skills_to_develop: list[str] = Field(default_factory=list)


class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week: int = Field(ge=1)
    title: str = Field(max_length=100)
    description: str = Field(max_length=300)
    success_criteria: str = Field(max_length=200)


class CareerCoachOutput(BaseModel):
    """Pass 3c E3 verbatim.

    handoff_requests: plural list per spec lines 696 + 739. Never
    populated by the D12 prompt (Option B). D13 may flip this when
    mandatory chain infrastructure lands.
    """

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(max_length=200)
    current_state_assessment: str
    plan: CareerPlan
    immediate_concerns: list[str] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    suggested_next_action: str = Field(max_length=300)
    handoff_requests: list[HandoffRequest] = Field(
        default_factory=list,
        description=(
            "D12 (Option B): NEVER populated. Supervisor reads "
            "handoff_targets from capability.py for up-front chain "
            "construction. Structured post-hoc handoff waits for D13."
        ),
    )


__all__ = [
    "CareerCoachOutput",
    "CareerPlan",
    "Milestone",
    "ProjectRef",
    "WeeklyFocus",
]
