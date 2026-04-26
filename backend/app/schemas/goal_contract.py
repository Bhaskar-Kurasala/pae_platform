import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Motivation = Literal["career_switch", "skill_up", "curiosity", "interview"]
# P3 3B #5: fixed buckets so we can drive realistic plan density without
# pretending to distinguish "7 vs 9 hrs/wk".
WeeklyHours = Literal["3-5", "6-10", "11+"]


class GoalContractBase(BaseModel):
    motivation: Motivation
    deadline_months: int = Field(ge=1, le=60)
    success_statement: str = Field(min_length=10, max_length=500)
    weekly_hours: WeeklyHours | None = None
    target_role: str | None = Field(default=None, max_length=128)


class GoalContractCreate(GoalContractBase):
    pass


class GoalContractUpdate(BaseModel):
    motivation: Motivation | None = None
    deadline_months: int | None = Field(default=None, ge=1, le=60)
    success_statement: str | None = Field(default=None, min_length=10, max_length=500)
    weekly_hours: WeeklyHours | None = None
    target_role: str | None = Field(default=None, max_length=128)


class GoalContractResponse(GoalContractBase):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    days_remaining: int = 0
