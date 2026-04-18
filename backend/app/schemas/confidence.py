"""Pydantic schemas for confidence calibration (P3 3A-7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceReportCreate(BaseModel):
    """Student self-report: 1-5 integer, optional skill context."""

    value: int = Field(ge=1, le=5)
    skill_id: uuid.UUID | None = None
    asked_at: datetime | None = None


class ConfidenceReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    skill_id: uuid.UUID | None
    value: int
    asked_at: datetime | None
    answered_at: datetime
