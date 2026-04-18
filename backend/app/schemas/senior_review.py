from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["approve", "request_changes", "comment"]
Severity = Literal["nit", "suggestion", "concern", "blocking"]


class SeniorReviewRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=16_000)
    problem_context: str | None = Field(default=None, max_length=2_000)


class SeniorReviewComment(BaseModel):
    line: int = Field(..., ge=1)
    severity: Severity
    message: str
    suggested_change: str | None = None


class SeniorReviewResponse(BaseModel):
    verdict: Verdict
    headline: str
    strengths: list[str]
    comments: list[SeniorReviewComment]
    next_step: str
