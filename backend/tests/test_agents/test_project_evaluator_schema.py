"""D14c CP1 — schema + capability + agent registration tests.

Pins the foundation work for project_evaluator migration:
  • ProjectEvaluatorInput accepts the spec'd shape (rubric_id dropped
    per D-2) and rejects bad shape
  • ProjectEvaluatorOutput validates with all nested types
    (DimensionScore, PortfolioEntryDraft) and rejects max_length /
    Field-bound violations
  • rubric_available bool flag is required (D-E load-bearing)
  • Capability is registered, available_now=True, reflects D14c CP1
    Pattern 18b preemptive calibration values
  • Agent class instantiates cleanly + AgenticBaseAgent contract is
    satisfied (run() returns a payload validating against
    ProjectEvaluatorOutput)
  • D-4 dual-rail refusal markers are exposed at module level

Tool-calling + dual-rail refusal routing + prompt-driven LLM behavior
land in CP2; real-MiniMax verification lands in CP3.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.capability import get_capability
from app.agents.project_evaluator import (
    NON_CAPSTONE_SUBMISSION_MARKER,
    RUBRIC_UNAVAILABLE_MARKER,
    ProjectEvaluatorAgent,
    _compose_answer,
)
from app.schemas.agents.project_evaluator import (
    DimensionScore,
    PortfolioEntryDraft,
    ProjectEvaluatorInput,
    ProjectEvaluatorOutput,
)
from app.schemas.supervisor import HandoffRequest


def _make_ctx() -> AgentContext:
    return AgentContext(
        user_id=uuid.uuid4(),
        chain=CallChain.start_root(caller="test"),
        session=MagicMock(spec=AsyncSession),
        extra={"_llm_usage": []},
    )


def _make_minimal_draft() -> PortfolioEntryDraft:
    return PortfolioEntryDraft(
        title="Test draft",
        summary="Short summary.",
    )


def _make_minimal_output(
    *,
    rubric_available: bool = True,
    dimension_scores: list[DimensionScore] | None = None,
    overall_score: float = 0.85,
    title: str = "Capstone Eval",
    handoff_request: HandoffRequest | None = None,
) -> ProjectEvaluatorOutput:
    return ProjectEvaluatorOutput(
        overall_score=overall_score,
        dimension_scores=dimension_scores or [],
        narrative_feedback="Specific feedback referring to actual work.",
        portfolio_entry_draft=PortfolioEntryDraft(
            title=title, summary="Summary."
        ),
        rubric_available=rubric_available,
        handoff_request=handoff_request,
    )


# ── Input schema ───────────────────────────────────────────────────


class TestProjectEvaluatorInput:
    def test_minimal_input_validates(self) -> None:
        sid = uuid.uuid4()
        inp = ProjectEvaluatorInput(project_submission_id=sid)
        assert inp.project_submission_id == sid
        assert inp.specific_concerns == []
        assert inp.resolved_message() is None

    def test_full_input(self) -> None:
        sid = uuid.uuid4()
        inp = ProjectEvaluatorInput(
            project_submission_id=sid,
            specific_concerns=["focus on RAG retrieval", "check eval rubric"],
            user_message="Please evaluate my capstone.",
        )
        assert inp.project_submission_id == sid
        assert len(inp.specific_concerns) == 2
        assert inp.resolved_message() == "Please evaluate my capstone."

    def test_project_submission_id_required(self) -> None:
        with pytest.raises(ValidationError):
            ProjectEvaluatorInput()  # type: ignore[call-arg]

    def test_project_submission_id_must_be_uuid(self) -> None:
        with pytest.raises(ValidationError):
            ProjectEvaluatorInput(project_submission_id="not-a-uuid")  # type: ignore[arg-type]

    def test_specific_concerns_max_length(self) -> None:
        sid = uuid.uuid4()
        with pytest.raises(ValidationError):
            ProjectEvaluatorInput(
                project_submission_id=sid,
                specific_concerns=[f"c{i}" for i in range(11)],
            )

    def test_resolved_message_falls_back_through_synonyms(self) -> None:
        sid = uuid.uuid4()
        inp = ProjectEvaluatorInput(project_submission_id=sid, task="Evaluate me.")
        assert inp.resolved_message() == "Evaluate me."
        inp = ProjectEvaluatorInput(
            project_submission_id=sid, question="Is my project ready?"
        )
        assert inp.resolved_message() == "Is my project ready?"

    def test_extra_fields_ignored(self) -> None:
        """extra='ignore' for Supervisor-shape variability tolerance.
        Per D-2: rubric_id dropped, but a stray rubric_id from a
        legacy caller should be ignored, not raise."""
        sid = uuid.uuid4()
        inp = ProjectEvaluatorInput(
            project_submission_id=sid,
            rubric_id=str(uuid.uuid4()),  # type: ignore[call-arg]
            junk_field="x",  # type: ignore[call-arg]
        )
        assert inp.project_submission_id == sid
        assert not hasattr(inp, "rubric_id")
        assert not hasattr(inp, "junk_field")

    def test_user_message_max_length(self) -> None:
        sid = uuid.uuid4()
        with pytest.raises(ValidationError):
            ProjectEvaluatorInput(
                project_submission_id=sid, user_message="x" * 4001
            )


# ── Output sub-types ───────────────────────────────────────────────


class TestDimensionScore:
    def test_minimal_validates(self) -> None:
        ds = DimensionScore(
            dimension_name="architecture",
            rubric_criterion="Does the solution use appropriate patterns (RAG, agents)?",
            score=0.85,
            evidence="Uses LangGraph state machine in agents/moa.py.",
        )
        assert ds.dimension_name == "architecture"
        assert ds.score == 0.85

    def test_score_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension_name="x",
                rubric_criterion="y",
                score=-0.1,
                evidence="z",
            )

    def test_score_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension_name="x",
                rubric_criterion="y",
                score=1.5,
                evidence="z",
            )

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension_name="x",
                rubric_criterion="y",
                score=0.5,
                evidence="z",
                weight=2.0,  # type: ignore[call-arg]
            )

    def test_dimension_name_max_length(self) -> None:
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension_name="x" * 201,
                rubric_criterion="y",
                score=0.5,
                evidence="z",
            )


class TestPortfolioEntryDraft:
    def test_minimal_validates(self) -> None:
        draft = PortfolioEntryDraft(title="My Capstone", summary="A brief summary.")
        assert draft.title == "My Capstone"
        assert draft.key_strengths == []
        assert draft.artifacts_referenced == []

    def test_key_strengths_max_length(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioEntryDraft(
                title="t",
                summary="s",
                key_strengths=[f"k{i}" for i in range(6)],
            )

    def test_artifacts_referenced_max_length(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioEntryDraft(
                title="t",
                summary="s",
                artifacts_referenced=[f"a{i}" for i in range(11)],
            )

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioEntryDraft(
                title="t", summary="s", priority="high"  # type: ignore[call-arg]
            )


# ── Output schema (top-level) ──────────────────────────────────────


class TestProjectEvaluatorOutput:
    def test_minimal_output_validates(self) -> None:
        out = _make_minimal_output()
        assert out.overall_score == 0.85
        assert out.rubric_available is True
        assert out.handoff_request is None

    def test_rubric_available_required(self) -> None:
        """D-E load-bearing — rubric_available must be present."""
        with pytest.raises(ValidationError):
            ProjectEvaluatorOutput(  # type: ignore[call-arg]
                overall_score=0.0,
                narrative_feedback="x",
                portfolio_entry_draft=_make_minimal_draft(),
            )

    def test_rubric_unavailable_refusal_path(self) -> None:
        """D-E refusal: empty dimension_scores + rubric_available=False."""
        out = ProjectEvaluatorOutput(
            overall_score=0.0,
            dimension_scores=[],
            narrative_feedback=(
                "Rubric was not available for this submission; "
                "evaluation cannot be rubric-grounded."
            ),
            portfolio_entry_draft=PortfolioEntryDraft(
                title="Evaluation Pending — Rubric Unavailable",
                summary="See narrative.",
            ),
            rubric_available=False,
        )
        assert out.rubric_available is False
        assert out.dimension_scores == []
        assert out.overall_score == 0.0

    def test_dimension_scores_max_length(self) -> None:
        scores = [
            DimensionScore(
                dimension_name=f"d{i}",
                rubric_criterion=f"c{i}",
                score=0.5,
                evidence=f"e{i}",
            )
            for i in range(16)
        ]
        with pytest.raises(ValidationError):
            ProjectEvaluatorOutput(
                overall_score=0.5,
                dimension_scores=scores,
                narrative_feedback="x",
                portfolio_entry_draft=_make_minimal_draft(),
                rubric_available=True,
            )

    def test_overall_score_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ProjectEvaluatorOutput(
                overall_score=1.5,
                narrative_feedback="x",
                portfolio_entry_draft=_make_minimal_draft(),
                rubric_available=True,
            )

    def test_narrative_feedback_max_length(self) -> None:
        with pytest.raises(ValidationError):
            ProjectEvaluatorOutput(
                overall_score=0.5,
                narrative_feedback="x" * 5001,
                portfolio_entry_draft=_make_minimal_draft(),
                rubric_available=True,
            )

    def test_extra_top_level_field_rejected(self) -> None:
        """extra='forbid' on output ensures shape drift fails loudly."""
        with pytest.raises(ValidationError):
            ProjectEvaluatorOutput(
                overall_score=0.5,
                narrative_feedback="x",
                portfolio_entry_draft=_make_minimal_draft(),
                rubric_available=True,
                approved=True,  # type: ignore[call-arg]
            )

    def test_handoff_request_validates(self) -> None:
        """HandoffRequest shape integration; suggested_context is dict
        (D13 Bug 21 regression check)."""
        hr = HandoffRequest(
            target_agent="senior_engineer",
            reason="non-capstone code review",
            suggested_context={"submission_id": "abc"},
        )
        out = _make_minimal_output(handoff_request=hr)
        assert out.handoff_request is not None
        assert out.handoff_request.target_agent == "senior_engineer"
        assert isinstance(out.handoff_request.suggested_context, dict)


# ── Capability registration ────────────────────────────────────────


class TestProjectEvaluatorCapability:
    def test_capability_registered(self) -> None:
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert cap.name == "project_evaluator"

    def test_capability_inputs(self) -> None:
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert "project_submission_id" in cap.inputs_required
        assert "specific_concerns" in cap.inputs_optional
        # D-2: rubric_id must NOT be in either list
        assert "rubric_id" not in cap.inputs_required
        assert "rubric_id" not in cap.inputs_optional

    def test_capability_outputs(self) -> None:
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert "evaluation" in cap.outputs_provided
        assert "score" in cap.outputs_provided
        assert "portfolio_entry_draft" in cap.outputs_provided

    def test_capability_calibration_pattern_18b(self) -> None:
        """D-D Pattern 18b: preemptive 90s set at CP1 (spec
        typical_latency_ms × 4.5). CP4 attempted to tighten to 75s
        based on CP3 observed_max × 1.30 headroom, but the CP4 post-
        cutover smoke timed out at 75.05s on the same Phase 1 payload
        CP3 ran in 51.81s — MiniMax tail latency spread is wider than
        observed_max × 1.30 absorbs at n=2. Held at 90s preemptive.
        typical_latency_ms preserved from spec at 20000."""
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert cap.typical_latency_ms == 20000
        assert cap.timeout_override_seconds == 90

    def test_capability_cost(self) -> None:
        cap = get_capability("project_evaluator")
        assert cap is not None
        # Spec value preserved per D14c scope
        assert float(cap.typical_cost_inr) == 8.00

    def test_capability_handoff_targets(self) -> None:
        """handoff_targets=['portfolio_builder'] informational only;
        portfolio_builder is D17 work."""
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert cap.handoff_targets == ["portfolio_builder"]

    def test_capability_available_now(self) -> None:
        """D14c CP1 flips available_now=True."""
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert cap.available_now is True

    def test_capability_no_mandatory_validation(self) -> None:
        """D-C: no Critic, no mandatory validation chain."""
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert cap.requires_mandatory_validation_by is None
        assert cap.validation_input_adapter is None

    def test_capability_entitlement(self) -> None:
        cap = get_capability("project_evaluator")
        assert cap is not None
        assert cap.requires_entitlement is True
        assert cap.minimum_tier == "standard"


# ── Agent class ────────────────────────────────────────────────────


class TestProjectEvaluatorAgent:
    def test_instantiates(self) -> None:
        agent = ProjectEvaluatorAgent()
        assert agent.name == "project_evaluator"

    def test_input_schema_bound(self) -> None:
        agent = ProjectEvaluatorAgent()
        assert agent.input_schema is ProjectEvaluatorInput

    def test_primitive_flags(self) -> None:
        """Per D-A, D-B, D-C locked decisions."""
        agent = ProjectEvaluatorAgent()
        assert agent.uses_memory is True
        assert agent.uses_tools is True
        # D-A: orchestration owns handoff dispatch
        assert agent.uses_inter_agent is False
        # D-C: no Critic loop
        assert agent.uses_self_eval is False
        assert agent.uses_proactive is False

    def test_permissions_set(self) -> None:
        agent = ProjectEvaluatorAgent()
        assert "read:student_data" in agent.permissions
        assert "write:agent_memory" in agent.permissions
        assert "read:agent_memory" in agent.permissions
        assert "write:audit_log" in agent.permissions

    def test_callees_empty(self) -> None:
        """uses_inter_agent=False so no callees declared."""
        agent = ProjectEvaluatorAgent()
        assert agent.allowed_callees == ()

    def test_run_method_signature(self) -> None:
        """run() exists and is async. Behavioral smoke (LLM path,
        tool ordering, refusal routing) lives in
        test_project_evaluator_v2_stub_smoke.py per CP2."""
        agent = ProjectEvaluatorAgent()
        assert callable(agent.run)
        # async coroutine method
        import inspect
        assert inspect.iscoroutinefunction(agent.run)


# ── D-4 dual-rail refusal markers ──────────────────────────────────


class TestRefusalMarkers:
    """D-E + D-4 dual-rail markers exposed at module level so CP2
    user_block builder + tests can reference them by symbol rather
    than string-literal."""

    def test_rubric_unavailable_marker_exposed(self) -> None:
        assert RUBRIC_UNAVAILABLE_MARKER == "RUBRIC_UNAVAILABLE"

    def test_non_capstone_submission_marker_exposed(self) -> None:
        assert NON_CAPSTONE_SUBMISSION_MARKER == "NON_CAPSTONE_SUBMISSION"

    def test_markers_are_distinct(self) -> None:
        assert RUBRIC_UNAVAILABLE_MARKER != NON_CAPSTONE_SUBMISSION_MARKER


# ── Answer projection ──────────────────────────────────────────────


class TestComposeAnswer:
    def test_normal_evaluation_includes_score(self) -> None:
        out = _make_minimal_output(
            rubric_available=True, overall_score=0.85, title="My Capstone"
        )
        answer = _compose_answer(out)
        assert "My Capstone" in answer
        assert "85" in answer

    def test_refusal_path_omits_score(self) -> None:
        """For refusal paths the title carries the disclaimer; score
        is meaningless (always 0.0)."""
        out = _make_minimal_output(
            rubric_available=False,
            overall_score=0.0,
            title="Evaluation Pending — Rubric Unavailable",
        )
        answer = _compose_answer(out)
        assert "Evaluation Pending" in answer
        # No '/100' suffix on refusal paths
        assert "/100" not in answer
