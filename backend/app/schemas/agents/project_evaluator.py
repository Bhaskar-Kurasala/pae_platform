"""D14c / Pass 3c E9 — project_evaluator input + output schemas.

Single-shot content-generating agent (per D-A): each call evaluates ONE
capstone submission. Schema follows the D12 v2 + D13 + D14b conventions:
extra="forbid" on outputs, extra="ignore" on inputs (Supervisor shape
variability), nested types fully described, every Field bound enumerated.

Spec-vs-schema reconciliation (D14c CP1 architectural finding): Pass 3c
E9 spec referenced rubric storage at "course's course_content" but no
such table exists in the codebase. Actual schema:

  • exercise_submissions.id  → project_submission_id input field maps
    here. The submission row joins exercises (FK) where is_capstone
    distinguishes capstones from regular exercises.
  • exercises.rubric (JSON, nullable)  → the rubric_text the agent
    consumes; serialized to JSON-pretty for the prompt.

Per D14c locked decision D-2: rubric_id input field dropped — rubric is
implied by submission's exercise_id, no separate rubric registry exists.
Per D-3: project_submission_id maps to exercise_submissions.id (where
exercises.is_capstone=TRUE).

Per D-E rubric-grounding enforcement, the output schema includes a
load-bearing rubric_available bool flag — agent must explicitly indicate
whether evaluation was rubric-grounded. Per D-4 dual-rail: same flag is
also False when the submission is not a capstone (NON_CAPSTONE_SUBMISSION
refusal path).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.agents.agentic_base import AgentInput
from app.schemas.supervisor import HandoffRequest


# ── Input ──────────────────────────────────────────────────────────


class ProjectEvaluatorInput(AgentInput):
    """Per Pass 3c E9 capability declaration, with D14c CP1 corrections.

    `project_submission_id` maps to `exercise_submissions.id` (D-3). The
    submission's exercise_id (FK) is used by the agent's run() to look
    up the rubric via read_rubric_for_capstone (D-1: tool renamed from
    spec's read_rubric_for_course since rubric is per-exercise, not
    per-course in the actual schema).

    Per D-2: rubric_id field dropped from spec. Rubric is implied by
    submission; no separate rubric registry exists.

    Supervisor shape variability: user_message may also arrive as `task`
    or `question` per the Supervisor's per-flow framing convention
    (matches D12 v2 + D13 v2 + D14b input shape).
    """

    model_config = ConfigDict(extra="ignore")

    project_submission_id: uuid.UUID = Field(
        description=(
            "Maps to exercise_submissions.id. The submission's joined "
            "exercise must have is_capstone=TRUE; otherwise the agent "
            "routes to D-4 NON_CAPSTONE_SUBMISSION graceful refusal."
        ),
    )
    specific_concerns: list[str] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Optional caller-supplied concerns to weight in the "
            "evaluation (e.g., 'focus on RAG retrieval correctness'). "
            "Empty by default — agent grades to the rubric uniformly."
        ),
    )

    # Supervisor shape synonyms — agent uses resolved_message().
    user_message: str | None = Field(default=None, max_length=4_000)
    question: str | None = Field(default=None, max_length=4_000)
    task: str | None = Field(default=None, max_length=4_000)

    def resolved_message(self) -> str | None:
        """Pick the populated user-message field; supports the
        Supervisor's variable shape per D12 v2 + D13 v2 + D14b convention."""
        for field in (self.user_message, self.question, self.task):
            if field and field.strip():
                return field
        return None


# ── Output sub-types ───────────────────────────────────────────────


class DimensionScore(BaseModel):
    """One scored rubric dimension.

    Per D-E load-bearing enforcement: dimension_name MUST come from the
    actual rubric_text in user_block, not be invented. rubric_criterion
    MUST quote or closely paraphrase the rubric language for that
    dimension. The runtime + prompt enforce this; the schema captures
    the shape contract.
    """

    model_config = ConfigDict(extra="forbid")

    dimension_name: str = Field(
        max_length=200,
        description=(
            "Rubric dimension label from the actual rubric_text — e.g., "
            "'architecture', 'code_quality'. NOT invented; must "
            "correspond to a key/category present in rubric_text."
        ),
    )
    rubric_criterion: str = Field(
        max_length=1_000,
        description=(
            "The rubric criterion this score corresponds to — direct "
            "quote or close paraphrase of rubric_text content for this "
            "dimension. Per D-E, this is how we verify rubric-grounding."
        ),
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Normalized score for this dimension. 0.0 = not "
            "demonstrated; 1.0 = exemplary. Per-dimension weight is "
            "not encoded — overall_score is the agent's aggregation."
        ),
    )
    evidence: str = Field(
        max_length=2_000,
        description=(
            "Specific evidence from the submission backing this score. "
            "References concrete artifacts (file names, function names, "
            "design choices); not generic praise/criticism."
        ),
    )


class PortfolioEntryDraft(BaseModel):
    """Draft portfolio entry passed to D17 portfolio_builder.

    The agent produces this as a starter shape; portfolio_builder (D17)
    expands it into a full portfolio entry with formatting, context,
    and surfacing decisions. Per D-A, project_evaluator does NOT
    dispatch portfolio_builder itself — the orchestration layer reads
    handoff_targets and routes.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        max_length=300,
        description=(
            "Short portfolio entry title. For refusal paths (D-E "
            "rubric-unavailable, D-4 non-capstone) this becomes a "
            "conservative pending-state title rather than a real title."
        ),
    )
    summary: str = Field(
        max_length=1_500,
        description=(
            "1-3 paragraph summary suitable for a portfolio reader. "
            "Refusal paths populate this conservatively or with the "
            "disclaimer copy."
        ),
    )
    key_strengths: list[str] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Up to 5 evidence-backed strengths. Each must point to "
            "actual work in the submission, not be generic praise."
        ),
    )
    artifacts_referenced: list[str] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Specific files / functions / artifacts from the submission "
            "the entry references. Empty for refusal paths."
        ),
    )


# ── Output ─────────────────────────────────────────────────────────


class ProjectEvaluatorOutput(BaseModel):
    """Pass 3c E9 verbatim plus D14c CP1 field-shape detail.

    Per D-A (single-shot) and D-C (no Critic / no mandatory validation
    chain), the output is a complete evaluation package the
    orchestration layer can deliver to D17 portfolio_builder in one
    round trip.

    Per D-E + D-4 dual-rail: the rubric_available bool is the schema-
    level enforcement marker. True iff (a) the submission is a real
    capstone AND (b) the rubric was found AND (c) dimension_scores
    reference rubric_criterion content. False on either refusal path.

    handoff_request semantics per D11 Option B: populated only in two
    cases: (1) when caller's message explicitly requests downstream
    handling, or (2) D-4 NON_CAPSTONE_SUBMISSION path may suggest
    senior_engineer for non-capstone code review (the single legitimate
    handoff case). Otherwise None.
    """

    model_config = ConfigDict(extra="forbid")

    overall_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Normalized aggregate score across rubric dimensions. The "
            "agent's aggregation; not a simple mean (heavier weight on "
            "load-bearing dimensions per the rubric). 0.0 on refusal "
            "paths."
        ),
    )
    dimension_scores: list[DimensionScore] = Field(
        default_factory=list,
        max_length=15,
        description=(
            "Per-rubric-dimension breakdown. Empty on refusal paths "
            "(D-E or D-4) — per the prompt, do NOT invent dimensions "
            "when rubric is unavailable."
        ),
    )
    narrative_feedback: str = Field(
        max_length=5_000,
        description=(
            "Multi-paragraph qualitative feedback for the student. "
            "Specific to the submission (refers to actual work), not "
            "generic. Refusal paths populate this with the disclaimer "
            "copy described in the prompt."
        ),
    )
    portfolio_entry_draft: PortfolioEntryDraft = Field(
        description=(
            "Draft portfolio entry. Conservative on refusal paths; "
            "rich and evidence-backed when rubric_available=True."
        ),
    )
    rubric_available: bool = Field(
        description=(
            "Per D-E + D-4: True iff evaluation was rubric-grounded "
            "(submission is capstone AND rubric was found AND "
            "dimension_scores reference rubric content). False on "
            "either refusal path. The orchestration layer / "
            "portfolio_builder reads this flag to decide whether to "
            "surface the evaluation as authoritative or to flag for "
            "instructor review."
        ),
    )
    handoff_request: HandoffRequest | None = Field(
        default=None,
        description=(
            "Per D11 Option B: populated rarely. Two legitimate cases: "
            "(1) caller explicitly requests downstream handling, "
            "(2) D-4 NON_CAPSTONE_SUBMISSION path may suggest "
            "senior_engineer for line-level code review on non-capstone "
            "work. Otherwise None."
        ),
    )


__all__ = [
    "DimensionScore",
    "PortfolioEntryDraft",
    "ProjectEvaluatorInput",
    "ProjectEvaluatorOutput",
]
