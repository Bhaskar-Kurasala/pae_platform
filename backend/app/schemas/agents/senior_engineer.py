"""D11 / Pass 3c E2 — senior_engineer output schema.

The structured response every senior_engineer invocation returns.
Per Pass 3c E2 verbatim, with one field-level adjustment captured in
the implementation notes below: handoff_request remains
``Optional[HandoffRequest] = None`` and is **never populated by D11's
prompt** (handoff Option B per docs/followups/handoff-protocol-d11-d13.md).
The field is informational metadata that D13 will flip on when the
mock_interview deliverable lands.

Three modes share one schema:

  • pr_review     → verdict + headline + strengths + comments + next_step
  • chat_help     → explanation + (optional) code_suggestion
  • rubric_score  → score + dimension_scores + rubric_feedback

The mode field disambiguates which sub-set of fields the caller
should expect to be populated. Common fields (``patterns_observed``,
``handoff_request``) apply to all three modes.

Sandbox tools (run_in_sandbox, run_static_analysis, run_tests) are
deferred to D14. The schema does NOT carry execution-result fields;
when D14 lands sandbox the schema can be additively extended without
breaking the v1 contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.supervisor import HandoffRequest


class CodeComment(BaseModel):
    """One inline comment on a piece of submitted code.

    ``line`` is a model best-effort hint — the LLM eyeballs the code
    and reports a line number. Without sandbox execution there's no
    parser-extracted ground truth. Students reading "line 17" should
    also check 16 and 18 if 17 looks fine; complex control flow can
    push attribution off by 1-2 lines.
    """

    model_config = ConfigDict(extra="forbid")

    line: int | None = Field(
        default=None,
        description=(
            "1-based line number the comment refers to, or None for "
            "whole-file comments. Best-effort; not parser-verified."
        ),
    )
    severity: Literal["nit", "suggestion", "concern", "blocking"]
    message: str = Field(max_length=240)
    suggested_change: str | None = Field(
        default=None,
        description=(
            "Optional concrete replacement code or rewrite hint. "
            "Hard cap at 30 lines per Pass 3c E2 prompt constraint — "
            "longer suggestions should link to docs instead."
        ),
    )


class SeniorEngineerOutput(BaseModel):
    """Pass 3c E2 verbatim. Three modes, shared schema.

    Field-population rules:

      • mode="pr_review"    → verdict, headline, comments populated;
                              strengths + next_step usually populated
      • mode="chat_help"    → explanation populated; code_suggestion
                              optional
      • mode="rubric_score" → score, dimension_scores populated;
                              rubric_feedback populated

    Cross-mode invariants enforced by the prompt (not the schema —
    Pydantic-level validation would block legitimate edge cases):

      • Any comment.severity="blocking" → verdict MUST be
        "request_changes" (consistency rule preserved from legacy
        senior_engineer prompt).
      • patterns_observed entries become memory writes under the
        agent's `senior_engineer:pattern:{name}` key (Pass 3c E2 §A.5).
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["pr_review", "chat_help", "rubric_score"]

    # ── pr_review fields ──
    verdict: Literal["approve", "request_changes", "comment"] | None = None
    headline: str | None = Field(default=None, max_length=120)
    strengths: list[str] = Field(default_factory=list, max_length=3)
    comments: list[CodeComment] = Field(default_factory=list)
    next_step: str | None = Field(default=None, max_length=200)

    # ── chat_help fields ──
    explanation: str | None = None
    code_suggestion: str | None = None

    # ── rubric_score fields ──
    score: int | None = Field(default=None, ge=0, le=100)
    dimension_scores: dict[str, int] = Field(default_factory=dict)
    rubric_feedback: str | None = None

    # ── shared fields ──
    patterns_observed: list[str] = Field(
        default_factory=list,
        description=(
            "Recurring code patterns this student exhibits. Each entry "
            "becomes a memory write under "
            "senior_engineer:pattern:{slug}. Used for cross-submission "
            "pattern detection (e.g. 'bare-except in 3 of 4 reviews')."
        ),
    )
    handoff_request: HandoffRequest | None = Field(
        default=None,
        description=(
            "v1 (D11): NEVER populated. Per "
            "docs/followups/handoff-protocol-d11-d13.md the prompt "
            "instructs the LLM to mention handoff suggestions as text "
            "in next_step; structured handoff routing waits for D13. "
            "Field stays in the schema so D13 can flip the prompt "
            "without a schema change."
        ),
    )


__all__ = ["CodeComment", "SeniorEngineerOutput"]
