"""D13 / Pass 3c E7 — mock_interview input + output schemas.

Multi-turn structural shape:
  • session_id is the binding key. Absent on first turn (agent generates a
    UUID and includes in output); present on follow-up turns (client passes
    the value the agent emitted previously).
  • turn_kind discriminates which fields are populated in the output. Per
    Pass 3c E7 the four kinds are question / evaluation / feedback /
    session_summary. Pydantic discriminated unions on output would be
    cleaner statically but add per-turn-kind class scaffolding the prompt
    has to enumerate; we follow study_planner's convention (one output
    class with optional per-turn-kind fields + documented invariants).

Singular `handoff_request` per Pass 3c convention; populated ONLY on
turn_kind="session_summary" per D-2 (Option B post-session suggestion).
On every other turn_kind, handoff_request is None.

Memory keys (Pass 3c E7):
  • mock_interview:session:{session_id} — within-session turn log
  • mock_interview:weakness:{topic}     — cross-session weakness tracking

Output-text projection: top-level `answer` field stamped by run() per
docs/followups/output-text-projection-convention.md.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.agentic_base import AgentInput
from app.schemas.supervisor import HandoffRequest


# ── Input ──────────────────────────────────────────────────────────


# Format names are the canonical Literal allowlist — referenced by both
# input and output, so define once and reuse.
InterviewFormat = Literal["system_design", "coding", "behavioral", "take_home"]
TurnKind = Literal["question", "evaluation", "feedback", "session_summary"]
DifficultyLevel = Literal["junior", "mid", "senior", "staff"]


class MockInterviewInput(AgentInput):
    """Per Pass 3c E7 — supports multi-turn sessions via session_id.

    First turn: client sends mode + user_message + (optional) target_role
    + difficulty_level + specific_topic. session_id is None.
    Follow-up turns: client sends the same mode + the candidate's answer in
    user_message + the session_id the agent emitted on the prior turn.

    Supervisor shape variability: user_message may also arrive as `task` or
    `question` per the Supervisor's per-flow framing convention.
    """

    model_config = ConfigDict(extra="ignore")

    mode: InterviewFormat = Field(
        description="Interview format. system_design / coding / behavioral / take_home."
    )
    session_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Binds turns within an interview session. None on first turn "
            "(agent generates and emits in output); the value the agent "
            "emitted on subsequent turns."
        ),
    )

    # Supervisor shape synonyms — agent uses resolved_message().
    user_message: str | None = Field(default=None, max_length=4_000)
    question: str | None = Field(default=None, max_length=4_000)
    task: str | None = Field(default=None, max_length=4_000)

    # Optional structured hints.
    target_role: str | None = Field(default=None, max_length=200)
    difficulty_level: DifficultyLevel | None = Field(default=None)
    specific_topic: str | None = Field(default=None, max_length=200)

    def resolved_message(self) -> str | None:
        """Pick the populated user-message field; supports the
        Supervisor's variable shape per E4 / E5 convention."""
        for field in (self.user_message, self.question, self.task):
            if field and field.strip():
                return field
        return None


# ── Output sub-types ───────────────────────────────────────────────


class InterviewQuestion(BaseModel):
    """Populated on turn_kind="question" turns. The agent is presenting a
    question to the candidate and waiting for their answer."""

    model_config = ConfigDict(extra="forbid")

    question_text: str = Field(max_length=2_000, description="The question.")
    rubric_summary: str = Field(
        max_length=400,
        description=(
            "What an excellent answer would cover. Concise — used by the "
            "agent on the next turn to ground evaluation."
        ),
    )
    expected_minutes: int = Field(
        ge=1, le=120, description="How long this question should take."
    )


class TurnEvaluation(BaseModel):
    """Populated on turn_kind="evaluation" turns. The agent has received
    the candidate's answer and is rating it."""

    model_config = ConfigDict(extra="forbid")

    score_0_to_10: int = Field(ge=0, le=10)
    strengths: list[str] = Field(
        default_factory=list,
        description="Specific things the candidate did well.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Specific weaknesses or missing depth. Each item is also a "
            "candidate for cross-session weakness tracking."
        ),
    )
    follow_up_question: str | None = Field(
        default=None,
        max_length=1_000,
        description=(
            "Optional probe based on the answer. When present, the next "
            "turn is another question; when absent, advance to feedback."
        ),
    )


class TurnFeedback(BaseModel):
    """Populated on turn_kind="feedback" turns. The agent is providing
    consolidated feedback after evaluation, before session ends."""

    model_config = ConfigDict(extra="forbid")

    overall_assessment: str = Field(max_length=600)
    one_thing_to_practice: str = Field(
        max_length=300,
        description=(
            "The single most-impact area the candidate should drill before "
            "their next interview. Specific, actionable."
        ),
    )


class SessionSummary(BaseModel):
    """Populated on turn_kind="session_summary" turns. The agent is closing
    the session and may include a handoff_request (Option B)."""

    model_config = ConfigDict(extra="forbid")

    overall_score_0_to_100: int = Field(ge=0, le=100)
    headline: str = Field(max_length=200, description="One-sentence verdict.")
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(
        default_factory=list,
        description=(
            "Cross-session-trackable weaknesses. Each item is written to "
            "agent_memory under mock_interview:weakness:{topic} by the "
            "agent's run() after parsing."
        ),
    )
    suggested_next_action: str = Field(
        max_length=300,
        description=(
            "What the candidate should do next — practice X, revisit Y, "
            "schedule a senior_engineer code review, etc."
        ),
    )


class MockInterviewDimensionScore(BaseModel):
    """D15 CP4 / D-D — one rubric dimension scored on a session verdict.

    The four standard dimensions (clarity_of_questioning,
    directional_adherence, complexity_adaptation,
    technical_correctness) come from the role_transitions row's
    mock_interview_dimensions JSONB; the weights are mirrored from
    that row so the agent's aggregation is reproducible.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        max_length=200,
        description=(
            "Dimension name from the gate's mock_interview_dimensions "
            "(e.g., 'clarity_of_questioning'). MUST match a key the "
            "agent received in user_block; the runtime backstop "
            "verifies coverage at session_summary turns."
        ),
    )
    weight: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Per-dimension weight echoed from the gate definition. "
            "Across all dimensions in dimension_scores, weights MUST "
            "sum to 1.0 (the runtime backstop verifies; if the LLM "
            "drifts, the agent normalizes before emitting)."
        ),
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Score on this dimension. 0.0 = not demonstrated; 1.0 = "
            "exemplary. The agent grounds each score in evidence drawn "
            "from the session's prior turns."
        ),
    )
    evidence: str = Field(
        max_length=1_000,
        description=(
            "Specific evidence from the session backing this score. "
            "Cites concrete moments (e.g., 'in turn 3 the candidate "
            "asked clarifying questions about latency budget before "
            "designing'); not generic praise/criticism."
        ),
    )


class TransitionTarget(BaseModel):
    """Slug pair identifying the gate this session evaluates against."""

    model_config = ConfigDict(extra="forbid")

    from_role_slug: str = Field(
        max_length=64,
        description="Slug of the role being transitioned OUT of.",
    )
    to_role_slug: str = Field(
        max_length=64,
        description="Slug of the role being transitioned INTO.",
    )


class SessionVerdict(BaseModel):
    """D15 CP4 / D-D — multi-dimensional session-end verdict.

    Populated ONLY at session END (turn_kind='session_summary') AND
    only when the candidate's user_message indicated gate-prep intent
    so the agent fetched read_role_transition_gate. None otherwise:

      * General-practice sessions (no gate-prep intent) →
        session_verdict = None on every turn.
      * Mid-session turns (turn_kind != session_summary) →
        session_verdict = None (the verdict is computed at session END).
      * Gate lookup failed (transition not found / not adjacent) →
        session_verdict = None; the agent falls back to
        SessionSummary's existing 0-100 scoring.

    Aggregation rule (the runtime backstop verifies):
      weighted_score = sum(d.weight * d.score for d in dimension_scores)
      passed = weighted_score >= mock_interview_pass_threshold

    evaluate_student_against_gate (CP2) reads
    output_data.session_verdict.passed AND
    output_data.session_verdict.transition_target.to_role_slug to
    decide whether this session counts toward the
    'sessions_passed_in_window' aggregate. The metadata coupling that
    Pattern 18b flagged at CP2 resolves at this checkpoint.
    """

    model_config = ConfigDict(extra="forbid")

    weighted_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Aggregated weighted score: sum(weight * score) across all "
            "dimensions in dimension_scores. The runtime backstop "
            "asserts weights sum to 1.0 and weighted_score equals the "
            "computed sum within float tolerance."
        ),
    )
    passed: bool = Field(
        description=(
            "weighted_score >= the gate's mock_interview_pass_threshold."
        ),
    )
    dimension_scores: list[MockInterviewDimensionScore] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Per-dimension breakdown. Length matches the gate's "
            "mock_interview_dimensions count (4 in v1: "
            "clarity_of_questioning, directional_adherence, "
            "complexity_adaptation, technical_correctness)."
        ),
    )
    transition_target: TransitionTarget | None = Field(
        default=None,
        description=(
            "The gate this session targets. None when general-practice "
            "(no gate-prep intent detected). evaluate_student_against_"
            "gate reads to_role_slug to filter sessions for the "
            "passes-in-window aggregate."
        ),
    )


# ── Output ─────────────────────────────────────────────────────────


class MockInterviewOutput(BaseModel):
    """Pass 3c E7 — multi-turn output schema.

    Invariants (enforced via prompt + post-parse validation; not Pydantic
    itself because Pydantic discriminated unions on optional sub-types add
    surface area without strong gain):

      • session_id is ALWAYS populated. Agent generates on first turn if
        input session_id was None.
      • Exactly ONE of (question, evaluation, feedback, session_summary)
        is populated per turn; the rest are None. turn_kind tells the
        client which one to read.
      • handoff_request is populated ONLY on turn_kind="session_summary"
        AND only when the session surfaced a coding-round failure or a
        strategic readiness gap (per D-2 Option B). Always None otherwise.
      • mode is the same across all turns of a session (the client passes
        it on every turn; the agent echoes).
    """

    model_config = ConfigDict(extra="forbid")

    # Always populated, always echoed.
    session_id: uuid.UUID
    mode: InterviewFormat
    turn_kind: TurnKind

    # Exactly one of these is populated per turn.
    question: InterviewQuestion | None = None
    evaluation: TurnEvaluation | None = None
    feedback: TurnFeedback | None = None
    session_summary: SessionSummary | None = None

    # Only populated on session_summary turns; Option B (suggested handoff).
    handoff_request: HandoffRequest | None = Field(
        default=None,
        description=(
            "D13 (Option B per D-2): populated ONLY on "
            "turn_kind='session_summary'. Suggests senior_engineer when "
            "the session surfaced a coding-round failure, or career_coach "
            "when readiness gaps are strategic. Mid-session handoffs are "
            "not honored in v1; that capability is deferred to a future "
            "deliverable per D-2."
        ),
    )
    session_verdict: SessionVerdict | None = Field(
        default=None,
        description=(
            "D15 CP4 / D-D: structured multi-dimensional verdict for "
            "gate-prep sessions. Populated ONLY at "
            "turn_kind='session_summary' AND when the user_message "
            "indicated gate-prep intent (so the agent fetched the "
            "transition's mock_interview_dimensions). None otherwise. "
            "evaluate_student_against_gate reads passed + "
            "transition_target.to_role_slug to count this session "
            "toward 'sessions_passed_in_window'."
        ),
    )


__all__ = [
    "DifficultyLevel",
    "InterviewFormat",
    "InterviewQuestion",
    "MockInterviewDimensionScore",
    "MockInterviewInput",
    "MockInterviewOutput",
    "SessionSummary",
    "SessionVerdict",
    "TransitionTarget",
    "TurnEvaluation",
    "TurnFeedback",
    "TurnKind",
]
