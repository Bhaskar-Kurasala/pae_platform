"""SRS API schemas (P2-05)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SRSCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    concept_key: str
    prompt: str
    ease_factor: float
    interval_days: int
    repetitions: int
    next_due_at: datetime
    last_reviewed_at: datetime | None


class SRSReviewRequest(BaseModel):
    quality: int = Field(
        ge=0,
        le=5,
        description="SM-2 quality score: 0-2 wrong, 3 hard, 4 normal, 5 easy.",
    )


class SRSUpsertRequest(BaseModel):
    concept_key: str = Field(min_length=1, max_length=128)
    prompt: str = Field(default="", max_length=512)
