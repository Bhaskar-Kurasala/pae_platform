import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Motivation = Literal["career_switch", "skill_up", "curiosity", "interview"]


class GoalContractBase(BaseModel):
    motivation: Motivation
    deadline_months: int = Field(ge=1, le=60)
    success_statement: str = Field(min_length=10, max_length=500)


class GoalContractCreate(GoalContractBase):
    pass


class GoalContractUpdate(BaseModel):
    motivation: Motivation | None = None
    deadline_months: int | None = Field(default=None, ge=1, le=60)
    success_statement: str | None = Field(default=None, min_length=10, max_length=500)


class GoalContractResponse(GoalContractBase):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
