"""D12 / Pass 3c E6 — tailored_resume output schema.

Shape b agent: AgenticBaseAgent surface wraps tailored_resume_service.
The mandatory self-handoff to resume_reviewer is DEFERRED to D13
per Deferral B (docs/followups/tailored-resume-mandatory-validation-d13.md).

`unsupported_additions` field is present in the schema — resume_reviewer
would populate this on the deferred validation pass; in D12 it stays empty.

Output-text projection: top-level `answer` field stamped by run() per
docs/followups/output-text-projection-convention.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.supervisor import HandoffRequest


class ResumeChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(max_length=60)
    what_changed: str = Field(max_length=200)
    why: str = Field(max_length=200)


class TailoredResumeOutput(BaseModel):
    """Pass 3c E6 verbatim.

    unsupported_additions: field exists for forward compat with D13's
    mandatory validation pass; will be empty in D12 v1.

    handoff_request: singular, NEVER populated in D12 (Option B +
    Deferral B). D13 flips this when mandatory chain infrastructure lands.
    """

    model_config = ConfigDict(extra="forbid")

    tailored_resume: str
    changes_made: list[ResumeChange] = Field(default_factory=list)
    keyword_alignment_score: float = Field(ge=0.0, le=1.0)
    unsupported_additions: list[str] = Field(
        default_factory=list,
        description=(
            "Additions not backed by student evidence. Should be empty in "
            "well-generated output. Populated by the downstream resume_reviewer "
            "validation pass — deferred to D13 (Deferral B)."
        ),
    )
    ats_compatibility_notes: list[str] = Field(default_factory=list)
    handoff_request: HandoffRequest | None = Field(
        default=None,
        description=(
            "D12 (Option B + Deferral B): NEVER populated. Mandatory "
            "self-handoff to resume_reviewer for output validation is deferred "
            "to D13. See docs/followups/tailored-resume-mandatory-validation-d13.md."
        ),
    )


__all__ = [
    "ResumeChange",
    "TailoredResumeOutput",
]
