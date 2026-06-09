"""D13 CP1 — schema + capability + agent registration tests.

Pins the foundation work for mock_interview migration:
  • MockInterviewInput accepts the spec'd shape and rejects bad shape
  • MockInterviewOutput validates at all four turn_kinds
  • Capability is registered and reflects D13 calibration values
  • Agent class instantiates cleanly + the AgenticBaseAgent contract
    is satisfied (run() returns a payload validating against
    MockInterviewOutput).

Tool-calling + prompt-driven LLM behavior land in CP2; real-MiniMax
verification lands in CP3.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.mock_interview import MockInterviewAgent
from app.schemas.agents.mock_interview import (
    InterviewQuestion,
    MockInterviewInput,
    MockInterviewOutput,
    SessionSummary,
    TurnEvaluation,
    TurnFeedback,
)
from app.schemas.supervisor import HandoffRequest


def _make_ctx() -> AgentContext:
    return AgentContext(
        user_id=uuid.uuid4(),
        chain=CallChain.start_root(caller="test"),
        session=MagicMock(spec=AsyncSession),
        extra={"_llm_usage": []},
    )


# ── Input schema ───────────────────────────────────────────────────


class TestMockInterviewInput:
    def test_first_turn_no_session_id(self) -> None:
        """First turn: client sends mode + user_message; session_id None."""
        inp = MockInterviewInput(
            mode="behavioral",
            user_message="I want to practice for a senior backend interview.",
        )
        assert inp.session_id is None
        assert inp.mode == "behavioral"
        assert inp.resolved_message() == (
            "I want to practice for a senior backend interview."
        )

    def test_followup_turn_with_session_id(self) -> None:
        """Follow-up turn: client passes the session_id agent emitted."""
        sid = uuid.uuid4()
        inp = MockInterviewInput(
            mode="behavioral",
            session_id=sid,
            user_message="My answer to the previous question is...",
        )
        assert inp.session_id == sid

    def test_invalid_mode_rejected(self) -> None:
        """Bad mode value fails Pydantic Literal validation."""
        with pytest.raises(ValidationError):
            MockInterviewInput(mode="trivia", user_message="hi")

    def test_resolved_message_falls_back_through_synonyms(self) -> None:
        """Supervisor shape variability: question/task fields are synonyms."""
        inp = MockInterviewInput(mode="coding", task="Code review me.")
        assert inp.resolved_message() == "Code review me."

        inp = MockInterviewInput(mode="coding", question="Help me prep.")
        assert inp.resolved_message() == "Help me prep."

    def test_resolved_message_empty_when_all_none(self) -> None:
        inp = MockInterviewInput(mode="coding")
        assert inp.resolved_message() is None

    def test_invalid_difficulty_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MockInterviewInput(
                mode="system_design",
                user_message="x",
                difficulty_level="god-tier",  # type: ignore[arg-type]
            )


# ── Output schema ──────────────────────────────────────────────────


class TestMockInterviewOutput:
    def test_question_turn_validates(self) -> None:
        out = MockInterviewOutput(
            session_id=uuid.uuid4(),
            mode="system_design",
            turn_kind="question",
            question=InterviewQuestion(
                question_text="Design a URL shortener.",
                rubric_summary="Capacity, hashing, eventual consistency.",
                expected_minutes=45,
            ),
        )
        assert out.turn_kind == "question"
        assert out.question is not None
        assert out.evaluation is None
        assert out.feedback is None
        assert out.session_summary is None
        assert out.handoff_request is None

    def test_evaluation_turn_validates(self) -> None:
        out = MockInterviewOutput(
            session_id=uuid.uuid4(),
            mode="coding",
            turn_kind="evaluation",
            evaluation=TurnEvaluation(
                score_0_to_10=7,
                strengths=["clean structure", "edge case handling"],
                gaps=["missed time complexity discussion"],
                follow_up_question="What's the worst-case big-O?",
            ),
        )
        assert out.turn_kind == "evaluation"
        assert out.evaluation is not None
        assert out.evaluation.score_0_to_10 == 7
        assert out.evaluation.follow_up_question is not None

    def test_feedback_turn_validates(self) -> None:
        out = MockInterviewOutput(
            session_id=uuid.uuid4(),
            mode="behavioral",
            turn_kind="feedback",
            feedback=TurnFeedback(
                overall_assessment="Strong storytelling, weak on metrics.",
                one_thing_to_practice=(
                    "Quantify outcomes — concrete numbers, not 'a lot'."
                ),
            ),
        )
        assert out.feedback is not None
        assert out.feedback.one_thing_to_practice.startswith("Quantify")

    def test_session_summary_turn_with_handoff_validates(self) -> None:
        """session_summary turn may include a HandoffRequest (Option B per D-2)."""
        out = MockInterviewOutput(
            session_id=uuid.uuid4(),
            mode="coding",
            turn_kind="session_summary",
            session_summary=SessionSummary(
                overall_score_0_to_100=58,
                headline="Mid-level coding fundamentals; needs more DS&A reps.",
                strengths=["clean variable naming"],
                weaknesses=["graph algorithms", "amortized complexity"],
                suggested_next_action=(
                    "Practice 5 medium graph problems on LeetCode."
                ),
            ),
            handoff_request=HandoffRequest(
                target_agent="senior_engineer",
                reason=(
                    "Coding round revealed unfamiliarity with graph "
                    "algorithms; senior_engineer can do code-level review."
                ),
                handoff_type="suggested",
            ),
        )
        assert out.session_summary is not None
        assert out.handoff_request is not None
        assert out.handoff_request.target_agent == "senior_engineer"
        # D-2: D13 only emits suggested handoffs, not mandatory.
        assert out.handoff_request.handoff_type == "suggested"

    def test_invalid_turn_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MockInterviewOutput(
                session_id=uuid.uuid4(),
                mode="coding",
                turn_kind="introduction",  # type: ignore[arg-type]
            )

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MockInterviewOutput(
                session_id=uuid.uuid4(),
                mode="trivia",  # type: ignore[arg-type]
                turn_kind="question",
            )

    def test_score_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TurnEvaluation(score_0_to_10=11, strengths=[], gaps=[])

    def test_session_score_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionSummary(
                overall_score_0_to_100=150,
                headline="x",
                suggested_next_action="x",
            )


# ── Capability ─────────────────────────────────────────────────────


class TestMockInterviewCapability:
    def test_capability_registered_and_available_now(self) -> None:
        from app.agents.capability import get_capability

        cap = get_capability("mock_interview")
        assert cap is not None
        assert cap.available_now is True

    def test_capability_calibration(self) -> None:
        """D13 CP3 calibration from real-LLM measurement.

        Phase 1 measured P50 ~35s under MiniMax with self_eval Critic
        active (main agent ~17s + Critic ~16s + safety classifier 2s).
        The 3x formula on typical_latency_ms alone resolves below this,
        so we use timeout_override_seconds=60 — matching the D12 pattern
        for agents whose structural floor exceeds what typical_latency_ms
        expresses (career_coach=150, resume_reviewer=90, tailored_resume
        =120).
        """
        from app.agents.capability import get_capability, resolve_timeout_seconds

        cap = get_capability("mock_interview")
        assert cap is not None
        assert cap.typical_latency_ms == 12000
        assert cap.timeout_override_seconds == 60
        # Override takes precedence over the typical_latency_ms × 3 formula.
        assert resolve_timeout_seconds(cap) == 60.0

    def test_capability_handoff_targets_match_d2(self) -> None:
        """D-2 Option B: senior_engineer + career_coach are informational
        metadata; the actual handoff_request is emitted only on
        session_summary turns."""
        from app.agents.capability import get_capability

        cap = get_capability("mock_interview")
        assert cap is not None
        assert set(cap.handoff_targets) == {"senior_engineer", "career_coach"}


# ── Agent class ────────────────────────────────────────────────────


class TestMockInterviewAgent:
    def test_agent_instantiates(self) -> None:
        agent = MockInterviewAgent()
        assert agent.name == "mock_interview"
        assert agent.uses_memory is True
        assert agent.uses_tools is True
        assert agent.uses_inter_agent is True
        # First v2 agent to flip self_eval. Per D13 prompt: single-turn
        # smoke at CP3 verifies it doesn't break the agent path.
        assert agent.uses_self_eval is True
        assert agent.uses_proactive is False

    def test_agent_allowed_callees_match_d2(self) -> None:
        agent = MockInterviewAgent()
        assert set(agent.allowed_callees) == {"senior_engineer", "career_coach"}

    # NOTE: run()-path coverage moved to test_mock_interview_v2_stub_smoke.py
    # at CP2 (CP1 stubs returned without an LLM call; CP2 runs the real
    # path, which would leak cost from this file). That file mocks
    # build_llm and exercises all four turn_kinds + memory ordering.
