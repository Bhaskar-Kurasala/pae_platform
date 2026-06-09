"""tailored_resume → resume_reviewer adapter.

Maps `TailoredResumeOutput` to `ResumeReviewerInput` so the Supervisor
can auto-extend the dispatch chain after tailored_resume completes.
Per D13.5 D-D: the producer agent owns the adapter so each
(producer, validator) pair is co-located in code, not centralized in
Supervisor logic.

Schema audit (D13.5 Stage 1.d):
  TailoredResumeOutput.tailored_resume: str   →  ResumeReviewerInput.resume_text: str | None
  (1:1 mapping, no information loss for the validator's purpose)

  TailoredResumeOutput.changes_made, .keyword_alignment_score,
  .ats_compatibility_notes — not consumed by ResumeReviewerInput; the
  validator focuses on unsupported claims, not the changes themselves.

  ResumeReviewerInput.target_role — TailoredResumeOutput does NOT carry
  the original target_role (it was on the input). The adapter cannot
  thread it without orchestrator support; we leave it None and let
  resume_reviewer infer from the resume body. Acceptable: validator's
  primary job is unsupported-claims detection, which doesn't need the
  role.

  ResumeReviewerInput.specific_concerns — populated with the canonical
  validation focus list per the D13.5 mandatory-validation contract.
"""

from __future__ import annotations

from typing import Any

from app.agents.resume_reviewer_v2 import ResumeReviewerInput
from app.schemas.agents.tailored_resume import TailoredResumeOutput


def tailored_resume_to_reviewer_input(
    output: TailoredResumeOutput | dict[str, Any],
) -> ResumeReviewerInput:
    """Map TailoredResumeOutput → ResumeReviewerInput.

    Used by the Supervisor's chain construction when tailored_resume
    completes and its capability declares
    `requires_mandatory_validation_by="resume_reviewer"`.

    Accepts either:
      • A TailoredResumeOutput Pydantic instance (clean unit-test path)
      • A dict (production path — `call_agent` returns the agent's
        payload as a dict via `output.model_dump(mode="json")` per the
        AgenticBaseAgent run() contract)

    The dual-input shape lets unit tests pass typed models directly
    while production dispatch threads the dict that already exists,
    avoiding a redundant model_validate at the dispatch layer.

    The validator runs against the tailored resume text (not the
    original) and surfaces any unsupported claims back into the
    user-facing response per D-C (compositional, not gating).
    """
    if isinstance(output, TailoredResumeOutput):
        tailored_text = output.tailored_resume
    elif isinstance(output, dict):
        tailored_text = output.get("tailored_resume", "")
        if not isinstance(tailored_text, str):
            raise ValueError(
                "tailored_resume_to_reviewer_input: 'tailored_resume' "
                f"key has unexpected type {type(tailored_text).__name__}"
            )
    else:
        raise TypeError(
            "tailored_resume_to_reviewer_input expects "
            "TailoredResumeOutput or dict, got "
            f"{type(output).__name__}"
        )

    return ResumeReviewerInput(
        resume_text=tailored_text,
        # specific_concerns scopes the validator's review to the
        # mandatory-validation contract rather than a full critique;
        # matches the D13 deferral doc's Step 3 spec.
        specific_concerns=["unsupported_claims", "ats_compatibility"],
    )


__all__ = ["tailored_resume_to_reviewer_input"]
