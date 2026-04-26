"""Schemas for the unified /practice surface."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.senior_review import SeniorReviewResponse


class PracticeReviewRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=16_000)
    problem_id: uuid.UUID | None = None
    problem_context: str | None = Field(default=None, max_length=2_000)


class PracticeReviewResponse(BaseModel):
    id: uuid.UUID
    problem_id: uuid.UUID | None
    review: SeniorReviewResponse
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PracticeReviewListItem(BaseModel):
    id: uuid.UUID
    problem_id: uuid.UUID | None
    review: SeniorReviewResponse
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
