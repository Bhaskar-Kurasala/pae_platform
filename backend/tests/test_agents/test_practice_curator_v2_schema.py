"""D14b CP1 — schema + capability + agent registration tests.

Pins the foundation work for practice_curator migration:
  • PracticeCuratorInput accepts the spec'd shape and rejects bad shape
  • PracticeCuratorOutput validates with all nested types (Exercise,
    TestCase, Hint) and rejects max_length / Literal violations
  • Capability is registered and reflects D14b CP1 calibration values
  • Agent class instantiates cleanly + AgenticBaseAgent contract is
    satisfied (run() returns a payload validating against
    PracticeCuratorOutput).

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
from app.agents.practice_curator import PracticeCuratorAgent
from app.schemas.agents.practice_curator import (
    Exercise,
    Hint,
    PracticeCuratorInput,
    PracticeCuratorOutput,
    TestCase,
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


class TestPracticeCuratorInput:
    def test_empty_input_validates(self) -> None:
        """All fields optional — student says 'give me anything to practice'."""
        inp = PracticeCuratorInput()
        assert inp.concept_focus is None
        assert inp.exercise_type is None
        assert inp.difficulty_level is None
        assert inp.resolved_message() is None

    def test_full_constraint_input(self) -> None:
        inp = PracticeCuratorInput(
            concept_focus="recursion",
            exercise_type="coding",
            difficulty_level="easy",
            user_message="Give me a recursion drill.",
        )
        assert inp.concept_focus == "recursion"
        assert inp.exercise_type == "coding"
        assert inp.difficulty_level == "easy"
        assert inp.resolved_message() == "Give me a recursion drill."

    def test_invalid_exercise_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PracticeCuratorInput(exercise_type="trivia")  # type: ignore[arg-type]

    def test_invalid_difficulty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PracticeCuratorInput(difficulty_level="god-tier")  # type: ignore[arg-type]

    def test_resolved_message_falls_back_through_synonyms(self) -> None:
        """Supervisor shape variability: question/task fields are synonyms."""
        inp = PracticeCuratorInput(task="Drill me on RAG.")
        assert inp.resolved_message() == "Drill me on RAG."
        inp = PracticeCuratorInput(question="Help me practice.")
        assert inp.resolved_message() == "Help me practice."

    def test_concept_focus_max_length_enforced(self) -> None:
        with pytest.raises(ValidationError):
            PracticeCuratorInput(concept_focus="x" * 201)

    def test_extra_fields_ignored(self) -> None:
        """extra='ignore' for Supervisor-shape variability tolerance."""
        # Should not raise even with unknown field; field is silently dropped.
        inp = PracticeCuratorInput(concept_focus="x", junk_field="y")  # type: ignore[call-arg]
        assert inp.concept_focus == "x"
        assert not hasattr(inp, "junk_field")


# ── Output schema (top-level) ─────────────────────────────────────


def _make_minimal_exercise() -> Exercise:
    return Exercise(
        title="Test exercise",
        difficulty="easy",
        description="A simple test.",
    )


class TestPracticeCuratorOutput:
    def test_minimal_output_validates(self) -> None:
        out = PracticeCuratorOutput(
            exercise=_make_minimal_exercise(),
            expected_solution_shape="One short function.",
            estimated_time_minutes=15,
        )
        assert out.exercise.title == "Test exercise"
        assert out.starter_code is None
        assert out.evaluation_criteria == []
        assert out.hint_sequence == []
        assert out.handoff_request is None

    def test_full_output_validates(self) -> None:
        out = PracticeCuratorOutput(
            exercise=Exercise(
                title="LRU cache",
                concept_tags=["data structures", "caching"],
                difficulty="medium",
                description="Implement an LRU cache with O(1) ops.",
                constraints=["Must run in O(1) for get and put"],
                test_cases_visible=[
                    TestCase(
                        input_description="cache size 2; ops: put(1,1), put(2,2), get(1)",
                        expected_output_description="1",
                    ),
                ],
                test_cases_hidden=[
                    TestCase(
                        input_description="100 random ops with size 1",
                        expected_output_description="all gets return MRU put",
                    ),
                ],
            ),
            starter_code="class LRUCache:\n    def __init__(self, capacity): pass",
            expected_solution_shape="Class with dict + doubly-linked list.",
            evaluation_criteria=[
                "O(1) get and put operations",
                "Correct eviction policy",
            ],
            hint_sequence=[
                Hint(order=1, text="Think about what data structure gives O(1) lookups."),
                Hint(order=2, text="A dict alone can't track recency. What can?"),
            ],
            estimated_time_minutes=45,
        )
        assert len(out.exercise.test_cases_visible) == 1
        assert len(out.hint_sequence) == 2
        assert out.exercise.difficulty == "medium"

    def test_output_with_handoff_request(self) -> None:
        """Per D11 Option B: handoff_request when user explicitly
        requested an evaluation flow."""
        out = PracticeCuratorOutput(
            exercise=_make_minimal_exercise(),
            expected_solution_shape="x",
            estimated_time_minutes=15,
            handoff_request=HandoffRequest(
                target_agent="senior_engineer",
                reason="Student requested code-level review post-attempt.",
                handoff_type="suggested",
            ),
        )
        assert out.handoff_request is not None
        assert out.handoff_request.target_agent == "senior_engineer"
        assert out.handoff_request.handoff_type == "suggested"

    def test_invalid_difficulty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Exercise(
                title="x",
                difficulty="ultra-hard",  # type: ignore[arg-type]
                description="x",
            )

    def test_estimated_time_below_floor_rejected(self) -> None:
        """5 min floor — anything shorter is too trivial to be a 'practice'."""
        with pytest.raises(ValidationError):
            PracticeCuratorOutput(
                exercise=_make_minimal_exercise(),
                expected_solution_shape="x",
                estimated_time_minutes=4,
            )

    def test_estimated_time_above_ceiling_rejected(self) -> None:
        """180 min (3h) ceiling — anything longer is a project, not a practice."""
        with pytest.raises(ValidationError):
            PracticeCuratorOutput(
                exercise=_make_minimal_exercise(),
                expected_solution_shape="x",
                estimated_time_minutes=181,
            )

    def test_extra_top_level_field_rejected(self) -> None:
        """extra='forbid' on output; D13 strip_extra_fields handles
        drift before validation. This pins the schema-level rejection."""
        with pytest.raises(ValidationError):
            PracticeCuratorOutput(
                exercise=_make_minimal_exercise(),
                expected_solution_shape="x",
                estimated_time_minutes=15,
                extra_field="leak",  # type: ignore[call-arg]
            )

    def test_max_5_visible_test_cases(self) -> None:
        with pytest.raises(ValidationError):
            Exercise(
                title="x",
                difficulty="easy",
                description="x",
                test_cases_visible=[
                    TestCase(input_description=str(i), expected_output_description="y")
                    for i in range(6)
                ],
            )

    def test_max_5_hints(self) -> None:
        with pytest.raises(ValidationError):
            PracticeCuratorOutput(
                exercise=_make_minimal_exercise(),
                expected_solution_shape="x",
                estimated_time_minutes=15,
                hint_sequence=[
                    Hint(order=i, text=f"hint {i}") for i in range(1, 7)
                ],
            )

    def test_concept_tags_capped_at_10(self) -> None:
        with pytest.raises(ValidationError):
            Exercise(
                title="x",
                difficulty="easy",
                description="x",
                concept_tags=["t" + str(i) for i in range(11)],
            )

    def test_description_max_length(self) -> None:
        with pytest.raises(ValidationError):
            Exercise(
                title="x",
                difficulty="easy",
                description="x" * 3001,
            )


# ── Nested types ──────────────────────────────────────────────────


class TestNestedTypes:
    def test_test_case_validates(self) -> None:
        tc = TestCase(
            input_description="empty list",
            expected_output_description="[]",
        )
        assert tc.input_description == "empty list"

    def test_test_case_max_length(self) -> None:
        with pytest.raises(ValidationError):
            TestCase(
                input_description="x" * 501,
                expected_output_description="y",
            )

    def test_hint_order_floor(self) -> None:
        with pytest.raises(ValidationError):
            Hint(order=0, text="x")

    def test_hint_order_ceiling(self) -> None:
        with pytest.raises(ValidationError):
            Hint(order=11, text="x")

    def test_hint_text_max_length(self) -> None:
        with pytest.raises(ValidationError):
            Hint(order=1, text="x" * 1001)

    def test_test_case_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TestCase(
                input_description="x",
                expected_output_description="y",
                extra_field="leak",  # type: ignore[call-arg]
            )


# ── Capability ─────────────────────────────────────────────────────


class TestPracticeCuratorCapability:
    def test_capability_registered_and_available(self) -> None:
        from app.agents.capability import get_capability

        cap = get_capability("practice_curator")
        assert cap is not None
        assert cap.available_now is True

    def test_capability_calibration(self) -> None:
        """D14b CP3 calibration from real-LLM measurement.

        Phase 1 + Phase 3 timed out at 30s under MiniMax; P2 succeeded
        at 29.1s — practice_curator's structured exercise output
        consistently lands at the 30s floor under MiniMax thinking-block
        overhead. timeout_override_seconds=60 sets a hard 60s budget,
        matching the D13 mock_interview pattern. typical_latency_ms
        stays at 8000 (Pass 3c E8 spec value) as the no-overhead
        baseline for downstream consumers.
        """
        from app.agents.capability import get_capability, resolve_timeout_seconds

        cap = get_capability("practice_curator")
        assert cap is not None
        assert cap.typical_latency_ms == 8000
        assert cap.timeout_override_seconds == 60
        # Override takes precedence over the formula.
        assert resolve_timeout_seconds(cap) == 60.0

    def test_capability_handoff_targets(self) -> None:
        """D-A: handoff_targets is informational only; orchestration
        layer reads it but the agent itself doesn't dispatch (the
        agent class has uses_inter_agent=False)."""
        from app.agents.capability import get_capability

        cap = get_capability("practice_curator")
        assert cap is not None
        assert cap.handoff_targets == ["senior_engineer"]

    def test_capability_no_mandatory_validation(self) -> None:
        """D-C: no mandatory validation chain."""
        from app.agents.capability import get_capability

        cap = get_capability("practice_curator")
        assert cap is not None
        assert cap.requires_mandatory_validation_by is None
        assert cap.validation_input_adapter is None


# ── Agent class ────────────────────────────────────────────────────


class TestPracticeCuratorAgent:
    def test_agent_instantiates(self) -> None:
        agent = PracticeCuratorAgent()
        assert agent.name == "practice_curator"
        assert agent.uses_memory is True
        assert agent.uses_tools is True
        # D-A: orchestration owns inter-agent dispatch.
        assert agent.uses_inter_agent is False
        # D-C: no Critic loop.
        assert agent.uses_self_eval is False
        assert agent.uses_proactive is False

    def test_agent_allowed_callees_empty(self) -> None:
        """uses_inter_agent=False ⇒ no callees declared."""
        agent = PracticeCuratorAgent()
        assert agent.allowed_callees == ()

    # NOTE: run()-path coverage moved to test_practice_curator_v2_stub_smoke.py
    # at CP2 (CP1 stubs returned without an LLM call; CP2 runs the real
    # path, which would leak cost from this file). That file mocks
    # build_llm and exercises all five exercise-type paths + handoff
    # gating + extra-field stripping + truncation. Pattern matches
    # D13 closure's Pattern 17 lesson (first-flip primitive tests must
    # not silently leak cost when the agent's stub becomes a real-LLM
    # path at CP2 transition).
