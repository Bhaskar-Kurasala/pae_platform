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


__all__ = [
    "DifficultyLevel",
    "InterviewFormat",
    "InterviewQuestion",
    "MockInterviewInput",
    "MockInterviewOutput",
    "SessionSummary",
    "TurnEvaluation",
    "TurnFeedback",
    "TurnKind",
]
