"""Schemas for the unified /practice surface."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.senior_review import SeniorReviewResponse


class RunOutputSnapshot(BaseModel):
    """Snapshot of the sandbox run the student just executed.

    When the frontend sends this, the reviewer is allowed to *cite* the
    outcome (exit code, stderr tail) rather than reasoning about code as
    pure text. The agent prompt is updated to distinguish "received run
    results — cite them" from "no run results — reason about behavior".
    """

    stdout: str = Field(default="", max_length=4_000)
    stderr: str = Field(default="", max_length=4_000)
    exit_code: int | None = None
    timed_out: bool = False
    quality_score: int | None = Field(default=None, ge=0, le=100)
    quality_summary: str | None = Field(default=None, max_length=400)


class PracticeReviewRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=16_000)
    problem_id: uuid.UUID | None = None
    problem_context: str | None = Field(default=None, max_length=2_000)
    run_output: RunOutputSnapshot | None = None


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
