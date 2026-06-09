"""D14b / Pass 3c E8 — practice_curator input + output schemas.

Single-shot content-generating agent (per D-A): each call produces ONE
exercise. No session_id, no multi-turn state. Schema follows the D12 v2
+ D13 conventions: extra="forbid" on outputs, extra="ignore" on inputs
(Supervisor shape variability), nested types fully described, every
Literal allowlist enumerated.

Per Pass 3c E8 spec at lines 1192-1212. The spec declares
PracticeCuratorOutput + Exercise but doesn't show TestCase or Hint
field shapes; D14b CP1 fixes those.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.agentic_base import AgentInput
from app.schemas.supervisor import HandoffRequest


# Format names — referenced by both input and output.
ExerciseType = Literal[
    "coding",
    "debugging",
    "system_design",
    "prompt_engineering",
    "evaluation_rubric",
]
DifficultyLevel = Literal["easy", "medium", "hard"]
# D15 CP4: D-E bank-vs-generative source flag. Optional metadata so
# downstream observability can distinguish curated bank selections from
# generative fallback. None on legacy / pre-D15 rows.
ExerciseSource = Literal["curated", "generated"]


# ── Input ──────────────────────────────────────────────────────────


class PracticeCuratorInput(AgentInput):
    """Per Pass 3c E8 capability declaration.

    All three "constraint" fields (concept_focus, exercise_type,
    difficulty_level) are optional. When None, the agent picks based on
    student state recalled from memory + DB. When set, the agent
    honors them as hard constraints on the generated exercise.

    Supervisor shape variability: user_message may also arrive as
    `task` or `question` per the Supervisor's per-flow framing
    convention (matches D12 v2 + D13 v2 input shape).
    """

    model_config = ConfigDict(extra="ignore")

    # Constraint fields per Pass 3c E8 inputs_optional.
    concept_focus: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Free-form concept the student wants to drill (e.g., "
            "'recursion', 'RAG retrieval'). When None, agent picks "
            "from student's weakest concept per memory recall."
        ),
    )
    exercise_type: ExerciseType | None = Field(
        default=None,
        description=(
            "Exercise format. When None, agent picks based on "
            "student's recent activity + concept_focus."
        ),
    )
    difficulty_level: DifficultyLevel | None = Field(
        default=None,
        description=(
            "Difficulty. When None, agent calibrates to student's "
            "current edge of mastery per recent submissions."
        ),
    )

    # Supervisor shape synonyms — agent uses resolved_message().
    user_message: str | None = Field(default=None, max_length=4_000)
    question: str | None = Field(default=None, max_length=4_000)
    task: str | None = Field(default=None, max_length=4_000)

    def resolved_message(self) -> str | None:
        """Pick the populated user-message field; supports the
        Supervisor's variable shape per D12 v2 + D13 v2 convention."""
        for field in (self.user_message, self.question, self.task):
            if field and field.strip():
                return field
        return None


# ── Output sub-types ───────────────────────────────────────────────


class TestCase(BaseModel):
    """One test case for an exercise.

    D14b CP1 design: descriptions only (not actual code/data) at the
    schema level. Rationale: the agent is generating exercise *prompts*
    for students, not executable test fixtures. Actual values live
    inside description text when the exercise needs concrete examples.
    If a future deliverable requires structured test data (e.g.,
    sandbox-driven verification per D-B follow-up), extend this schema
    with optional `input_value: str | None` + `expected_value: str |
    None` fields rather than reshaping.

    Note: __test__ = False suppresses pytest's class-collection
    heuristic (any `Test*` class is auto-collected). Spec name is
    `TestCase` per Pass 3c E8; we keep it for fidelity.
    """

    __test__ = False  # not a pytest test class

    model_config = ConfigDict(extra="forbid")

    input_description: str = Field(
        max_length=500,
        description=(
            "Human-readable description of the input. May include "
            "concrete values inline (e.g., 'list [1, 2, 3]')."
        ),
    )
    expected_output_description: str = Field(
        max_length=500,
        description=(
            "Human-readable description of the expected output. May "
            "include concrete values inline."
        ),
    )


class Hint(BaseModel):
    """Progressive hint, unlocked one at a time per the spec.

    The `order` field pins ordering — students receive hints in
    ascending order. Capped at 10 to bound the hint sequence length.
    """

    model_config = ConfigDict(extra="forbid")

    order: int = Field(
        ge=1,
        le=10,
        description=(
            "1-based hint position. Students unlock hints in ascending "
            "order; lower-order hints are less revealing than higher."
        ),
    )
    text: str = Field(
        max_length=1_000,
        description="The hint itself; specific enough to be useful.",
    )


class Exercise(BaseModel):
    """Pass 3c E8 verbatim plus field-shape detail.

    The spec declares title, concept_tags, difficulty, description,
    constraints, test_cases_visible, test_cases_hidden. D14b CP1 adds
    field-level constraints (max_length, list caps).
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=200, description="Short exercise title.")
    concept_tags: list[str] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Concept labels — usually 1-3, capped at 10. Tags are used "
            "by the orchestration layer to track which concepts the "
            "student has practiced."
        ),
    )
    difficulty: DifficultyLevel = Field(
        description=(
            "Calibrated difficulty: easy = ~15-30min, medium = "
            "~30-60min, hard = ~60-180min. The agent's "
            "estimated_time_minutes is the per-exercise number."
        ),
    )
    description: str = Field(
        max_length=3_000,
        description=(
            "The problem statement — what the student needs to do. "
            "May include examples, constraints, and acceptance "
            "criteria inline."
        ),
    )
    constraints: list[str] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Solution-shape constraints (e.g., 'must run in O(n)', "
            "'no third-party libraries', 'must be type-annotated'). "
            "Distinct from test cases — these constrain HOW the "
            "student can solve the problem."
        ),
    )
    test_cases_visible: list[TestCase] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Test cases the student sees. Should be representative "
            "of the expected behavior; not edge cases."
        ),
    )
    test_cases_hidden: list[TestCase] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Test cases used by senior_engineer for evaluation. "
            "May probe edge cases, boundary conditions, or "
            "performance characteristics not visible to the student."
        ),
    )
    source: ExerciseSource | None = Field(
        default=None,
        description=(
            "D15 CP4 metadata: 'curated' when the exercise was selected "
            "from the student's accessible_curated_problems bank; "
            "'generated' when the agent generated it (D14b fallback "
            "behavior). None on legacy rows / when the agent didn't "
            "decide. Downstream observability reads this to track the "
            "bank-vs-generative ratio."
        ),
    )
    curated_exercise_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "When source='curated', the exercises.id of the selected "
            "platform exercise. None when source='generated'. Lets "
            "downstream consumers (orchestrator, portfolio_builder) "
            "link the practice attempt to the canonical exercise."
        ),
    )


# ── Output ─────────────────────────────────────────────────────────


class PracticeCuratorOutput(BaseModel):
    """Pass 3c E8 verbatim plus field-shape detail.

    Per D-A (single-shot) and D-C (no Critic / no mandatory
    validation), the output is a complete exercise package the
    orchestration layer can deliver to the student in one round trip.

    handoff_request semantics per D11 Option B: populated only when
    the user explicitly requests an evaluation flow (the orchestration
    layer recognizes this and dispatches senior_engineer afterward).
    """

    model_config = ConfigDict(extra="forbid")

    exercise: Exercise = Field(
        description="The generated exercise; primary content."
    )
    starter_code: str | None = Field(
        default=None,
        max_length=5_000,
        description=(
            "Optional scaffolding code the student starts from. None "
            "for non-coding exercise types or when the agent decides "
            "the student should write from scratch."
        ),
    )
    expected_solution_shape: str = Field(
        max_length=2_000,
        description=(
            "Description of what a correct solution looks like — NOT "
            "the answer itself. E.g., 'a recursive function with a "
            "base case and a reduction step' rather than the actual "
            "code. Used by senior_engineer for evaluation grounding."
        ),
    )
    evaluation_criteria: list[str] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Specific, observable criteria a senior_engineer would use "
            "to score the student's submission. Each criterion is one "
            "thing to check (e.g., 'handles empty input gracefully', "
            "'uses recursion not iteration')."
        ),
    )
    hint_sequence: list[Hint] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Up to 5 progressive hints, ordered by the Hint.order "
            "field. Students unlock one at a time."
        ),
    )
    estimated_time_minutes: int = Field(
        ge=5,
        le=180,
        description=(
            "Per-exercise time estimate. Should align with difficulty: "
            "easy 15-30, medium 30-60, hard 60-180. Lower bound 5 min "
            "for very simple drills; upper bound 180 min (3 hours) is "
            "the deliverable cap. NOTE: prompt provides tighter "
            "operational guidance (easy 15-30 floor); the schema's 5-min "
            "floor is intentional defense-in-depth — accommodates micro-"
            "drill use cases that may surface post-D14b without forcing "
            "a schema migration. Confirmed at CP1 closure."
        ),
    )
    handoff_request: HandoffRequest | None = Field(
        default=None,
        description=(
            "Per D11 Option B: populated only when the user explicitly "
            "requested an evaluation flow. Otherwise None. The "
            "orchestration layer reads this to decide whether to "
            "auto-dispatch senior_engineer for code review after the "
            "student submits."
        ),
    )


__all__ = [
    "DifficultyLevel",
    "Exercise",
    "ExerciseSource",
    "ExerciseType",
    "Hint",
    "PracticeCuratorInput",
    "PracticeCuratorOutput",
    "TestCase",
]
