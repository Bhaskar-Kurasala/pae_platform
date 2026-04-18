from uuid import UUID

from pydantic import BaseModel


class PlannedActivityItem(BaseModel):
    day: int
    kind: str
    skill_id: UUID
    skill_slug: str
    minutes: int
    rationale: str


class FirstDayPlanResponse(BaseModel):
    daily_minutes_target: int
    activities: list[PlannedActivityItem]
