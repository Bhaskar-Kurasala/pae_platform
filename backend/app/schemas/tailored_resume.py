"""Pydantic schemas for the tailored resume agent."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IntakeQuestion(BaseModel):
    id: str
    label: str
    kind: str
    required: str  # "true" / "false" — kept as string to mirror the source


class QuotaState(BaseModel):
    allowed: bool
    reason: str
    remaining_today: int
    remaining_month: int
    reset_at: datetime | None = None


class IntakeStartResponse(BaseModel):
    """Returned by POST /tailored-resume/intake — drives the modal."""

    questions: list[IntakeQuestion]
    quota: QuotaState
    soft_gate: bool = Field(
        default=False,
        description="True when Resume.verdict == 'needs_work' — UI shows a nudge but allows override.",
    )


class IntakeStartRequest(BaseModel):
    jd_text: str = Field(min_length=20)
    jd_id: uuid.UUID | None = None


class GenerateRequest(BaseModel):
    jd_text: str = Field(min_length=20)
    jd_id: uuid.UUID | None = None
    intake_answers: dict[str, Any] = Field(default_factory=dict)


class TailoredResumeResponse(BaseModel):
    id: uuid.UUID
    content: dict[str, Any]
    cover_letter: dict[str, Any]
    validation: dict[str, Any]
    quota: QuotaState
    cost_inr: float


class QuotaResponse(BaseModel):
    quota: QuotaState
