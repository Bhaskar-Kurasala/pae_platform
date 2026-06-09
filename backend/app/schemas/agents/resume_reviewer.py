"""D12 / Pass 3c E5 — resume_reviewer output schema.

Singular `handoff_request` per E5 spec.
NEVER populated in D12 (Option B).

Output-text projection: top-level `answer` field stamped by run() per
docs/followups/output-text-projection-convention.md.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.supervisor import HandoffRequest


class UnsupportedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_text: str = Field(max_length=300)
    missing_evidence: str = Field(max_length=300)
    suggested_action: Literal["remove", "soften", "add_evidence", "verify_with_student"]


class Accomplishment(BaseModel):
    """An accomplishment the student undersold on their resume."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(max_length=300)
    evidence_source: str = Field(max_length=200)
    suggested_resume_text: str = Field(max_length=300)


class ResumeSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(max_length=60)
    original_text: str | None = Field(default=None, max_length=400)
    suggested_text: str = Field(max_length=400)
    rationale: str = Field(max_length=200)


class ResumeReviewerOutput(BaseModel):
    """Pass 3c E5 verbatim.

    handoff_request: singular, NEVER populated in D12 (Option B).
    """

    model_config = ConfigDict(extra="forbid")

    overall_score: int = Field(ge=0, le=100)
    headline_assessment: str = Field(max_length=200)
    strengths: list[str] = Field(default_factory=list)
    issues: list[ResumeSuggestion] = Field(default_factory=list)
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    underrepresented_accomplishments: list[Accomplishment] = Field(default_factory=list)
    suggested_changes: list[ResumeSuggestion] = Field(default_factory=list)
    handoff_request: HandoffRequest | None = Field(
        default=None,
        description=(
            "D12 (Option B): NEVER populated. Portfolio gap signals "
            "surface as text in suggested_changes. D13 may flip."
        ),
    )


__all__ = [
    "Accomplishment",
    "ResumeReviewerOutput",
    "ResumeSuggestion",
    "UnsupportedClaim",
]
