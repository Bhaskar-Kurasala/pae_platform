"""D15 CP4 — schema additions + agent-layer backstop unit tests.

Pins the architecture verified deterministically (without real LLM):

  practice_curator
    * Exercise.source field accepts "curated" | "generated" | None
    * curated_exercise_id field accepts string | None
    * _infer_exercise_source returns ("curated", <id>) when title matches
      a bank entry, ("generated", None) when bank is empty or no match

  project_evaluator
    * TransitionGateStatus model accepts the canonical shape
    * ProjectEvaluatorOutput.transition_gate_status field exists, default None
    * _enforce_gate_status returns None on refusal paths AND on terminal role
    * _enforce_gate_status returns canonical TransitionGateStatus when all
      sources align, with passes_threshold computed from
      overall_score >= capstone_threshold_required

  mock_interview
    * MockInterviewDimensionScore + TransitionTarget + SessionVerdict
      models accept canonical shapes
    * MockInterviewOutput.session_verdict field exists, default None
    * _detect_gate_prep_target fires on canonical phrases, returns None
      on neutral messages, prefers slug-form over spaced-form
    * _enforce_session_verdict returns None when not session_summary
    * _enforce_session_verdict returns None when gate not found
    * _enforce_session_verdict returns canonical verdict with all four
      dimensions when gate is found at session_summary turn
    * Weight sum = 1.0 across the canonical four dimensions

The real-LLM CP4 phases verify these architectures end-to-end under
MiniMax. P1+P2+P3 ship clean; P4 (mock_interview multi-turn) suffers
from Critic-retry session_id loss orthogonal to the schema work
(backstop is deterministically correct, but the multi-turn driver
can't reliably reach session_summary under retry pressure within
budget). These unit tests pin the architecture; Phase 4 real-LLM
verification at production scale lands when the orchestrator wires
session_id properly through the dispatch boundary.
"""

from __future__ import annotations

import uuid

import pytest

from app.agents.mock_interview import (
    _detect_gate_prep_target,
    _enforce_session_verdict,
)
from app.agents.practice_curator import _infer_exercise_source
from app.agents.project_evaluator import _enforce_gate_status
from app.schemas.agents.mock_interview import (
    MockInterviewDimensionScore,
    MockInterviewOutput,
    SessionSummary,
    SessionVerdict,
    TransitionTarget,
)
from app.schemas.agents.practice_curator import (
    Exercise,
    PracticeCuratorOutput,
)
from app.schemas.agents.project_evaluator import (
    PortfolioEntryDraft,
    ProjectEvaluatorOutput,
    TransitionGateStatus,
)


# ── practice_curator ──────────────────────────────────────────────────


def test_exercise_source_field_accepts_curated_or_generated() -> None:
    base = {
        "title": "Recursion drill",
        "concept_tags": ["recursion"],
        "difficulty": "easy",
        "description": "Implement a recursive factorial.",
    }
    e_curated = Exercise(**base, source="curated", curated_exercise_id="abc")
    assert e_curated.source == "curated"
    assert e_curated.curated_exercise_id == "abc"

    e_generated = Exercise(**base, source="generated")
    assert e_generated.source == "generated"
    assert e_generated.curated_exercise_id is None

    e_none = Exercise(**base)
    assert e_none.source is None
    assert e_none.curated_exercise_id is None


def test_exercise_source_field_rejects_invalid_literal() -> None:
    base = {
        "title": "X",
        "concept_tags": [],
        "difficulty": "easy",
        "description": "Y",
    }
    with pytest.raises(Exception):
        Exercise(**base, source="curatedx")  # type: ignore[arg-type]


def test_infer_exercise_source_curated_match_exact_title() -> None:
    accessible = {
        "accessible_curated_problems": [
            {"exercise_id": "ex-1", "title": "CLI AI tool", "is_capstone": True},
            {"exercise_id": "ex-2", "title": "FizzBuzz drill", "is_capstone": False},
        ]
    }
    src, eid = _infer_exercise_source("CLI AI tool", accessible)
    assert src == "curated"
    assert eid == "ex-1"


def test_infer_exercise_source_curated_match_substring() -> None:
    accessible = {
        "accessible_curated_problems": [
            {"exercise_id": "ex-1", "title": "FizzBuzz drill", "is_capstone": False},
        ]
    }
    src, eid = _infer_exercise_source("FizzBuzz", accessible)
    assert src == "curated"
    assert eid == "ex-1"


def test_infer_exercise_source_generated_when_bank_empty() -> None:
    accessible = {"accessible_curated_problems": []}
    src, eid = _infer_exercise_source("Anything", accessible)
    assert src == "generated"
    assert eid is None


def test_infer_exercise_source_generated_when_no_title_match() -> None:
    accessible = {
        "accessible_curated_problems": [
            {"exercise_id": "ex-1", "title": "Algorithm Practice", "is_capstone": False},
        ]
    }
    src, eid = _infer_exercise_source("Solve the Tower of Hanoi", accessible)
    assert src == "generated"
    assert eid is None


# ── project_evaluator ────────────────────────────────────────────────


def _make_minimal_pe_output(
    *,
    overall_score: float,
    rubric_available: bool,
) -> ProjectEvaluatorOutput:
    return ProjectEvaluatorOutput(
        overall_score=overall_score,
        dimension_scores=[],
        narrative_feedback="x" * 50,
        portfolio_entry_draft=PortfolioEntryDraft(
            title="t",
            summary="s",
        ),
        rubric_available=rubric_available,
    )


def test_transition_gate_status_accepts_canonical_shape() -> None:
    g = TransitionGateStatus(
        transition_from_role="ml_engineer",
        transition_to_role="genai_engineer",
        capstone_threshold_required=0.75,
        capstone_score_achieved=0.82,
        passes_threshold=True,
        gate_message="passes the gate",
    )
    assert g.passes_threshold is True


def test_pe_output_has_transition_gate_status_field_default_none() -> None:
    out = _make_minimal_pe_output(overall_score=0.5, rubric_available=False)
    assert out.transition_gate_status is None


def test_enforce_gate_status_none_on_refusal_path() -> None:
    out = _make_minimal_pe_output(overall_score=0.0, rubric_available=False)
    role_state = {
        "found": True,
        "current_role": {"slug": "ml_engineer", "is_terminal": False},
        "next_transition": {"target_role_slug": "genai_engineer"},
    }
    gate_def = {"found": True, "capstone_threshold": 0.75}
    assert _enforce_gate_status(
        output=out, role_state=role_state, gate_def=gate_def
    ) is None


def test_enforce_gate_status_none_on_terminal_role() -> None:
    out = _make_minimal_pe_output(overall_score=0.85, rubric_available=True)
    role_state = {
        "found": True,
        "current_role": {"slug": "senior_genai_engineer", "is_terminal": True},
    }
    gate_def = {"found": True, "capstone_threshold": 0.80}
    assert _enforce_gate_status(
        output=out, role_state=role_state, gate_def=gate_def
    ) is None


def test_enforce_gate_status_passes_when_score_meets_threshold() -> None:
    out = _make_minimal_pe_output(overall_score=0.82, rubric_available=True)
    role_state = {
        "found": True,
        "current_role": {"slug": "ml_engineer", "is_terminal": False},
        "next_transition": {"target_role_slug": "genai_engineer"},
    }
    gate_def = {"found": True, "capstone_threshold": 0.75}

    g = _enforce_gate_status(
        output=out, role_state=role_state, gate_def=gate_def
    )
    assert g is not None
    assert g.transition_from_role == "ml_engineer"
    assert g.transition_to_role == "genai_engineer"
    assert g.capstone_threshold_required == pytest.approx(0.75)
    assert g.capstone_score_achieved == pytest.approx(0.82)
    assert g.passes_threshold is True
    assert "0.82" in g.gate_message
    assert "0.75" in g.gate_message


def test_enforce_gate_status_fails_when_score_below_threshold() -> None:
    out = _make_minimal_pe_output(overall_score=0.60, rubric_available=True)
    role_state = {
        "found": True,
        "current_role": {"slug": "ml_engineer", "is_terminal": False},
        "next_transition": {"target_role_slug": "genai_engineer"},
    }
    gate_def = {"found": True, "capstone_threshold": 0.75}
    g = _enforce_gate_status(
        output=out, role_state=role_state, gate_def=gate_def
    )
    assert g is not None
    assert g.passes_threshold is False
    assert g.capstone_score_achieved == pytest.approx(0.60)


def test_enforce_gate_status_none_when_gate_not_found() -> None:
    out = _make_minimal_pe_output(overall_score=0.85, rubric_available=True)
    role_state = {
        "found": True,
        "current_role": {"slug": "ml_engineer", "is_terminal": False},
        "next_transition": {"target_role_slug": "genai_engineer"},
    }
    gate_def: dict = {}  # not found
    assert _enforce_gate_status(
        output=out, role_state=role_state, gate_def=gate_def
    ) is None


# ── mock_interview ────────────────────────────────────────────────────


def test_session_verdict_accepts_canonical_shape() -> None:
    sv = SessionVerdict(
        weighted_score=0.78,
        passed=True,
        dimension_scores=[
            MockInterviewDimensionScore(
                name="technical_correctness",
                weight=0.25,
                score=0.90,
                evidence="cited concrete BM25 + dense ranking choice",
            )
        ],
        transition_target=TransitionTarget(
            from_role_slug="ml_engineer",
            to_role_slug="genai_engineer",
        ),
    )
    assert sv.passed is True
    assert sv.transition_target.to_role_slug == "genai_engineer"


def test_mi_output_has_session_verdict_field_default_none() -> None:
    out = MockInterviewOutput(
        session_id=uuid.uuid4(),
        mode="system_design",
        turn_kind="question",
    )
    assert out.session_verdict is None


def test_detect_gate_prep_target_canonical_phrase() -> None:
    msg = "I'm preparing for the gate to genai_engineer; let's do a mock."
    assert _detect_gate_prep_target(msg, []) == "genai_engineer"


def test_detect_gate_prep_target_spaced_form() -> None:
    msg = "I want to prep for the data scientist gate."
    assert _detect_gate_prep_target(msg, []) == "data_scientist"


def test_detect_gate_prep_target_neutral_message_returns_none() -> None:
    msg = "Give me a system design question on caching."
    assert _detect_gate_prep_target(msg, []) is None


def test_detect_gate_prep_target_prefers_longest_spaced_match() -> None:
    msg = "Preparing for the senior genai engineer gate"
    assert _detect_gate_prep_target(msg, []) == "senior_genai_engineer"


def test_enforce_session_verdict_none_when_not_session_summary() -> None:
    out = MockInterviewOutput(
        session_id=uuid.uuid4(),
        mode="system_design",
        turn_kind="question",
    )
    assert _enforce_session_verdict(
        output=out,
        from_role_slug="ml_engineer",
        target_to_role="genai_engineer",
        gate_def={"found": True, "mock_interview_dimensions": {"a": 1.0},
                  "mock_interview_pass_threshold": 0.5},
    ) is None


def test_enforce_session_verdict_none_when_gate_not_found() -> None:
    out = MockInterviewOutput(
        session_id=uuid.uuid4(),
        mode="system_design",
        turn_kind="session_summary",
        session_summary=SessionSummary(
            overall_score_0_to_100=70,
            headline="ok",
            strengths=[],
            weaknesses=[],
            suggested_next_action="next",
        ),
    )
    assert _enforce_session_verdict(
        output=out,
        from_role_slug="ml_engineer",
        target_to_role="genai_engineer",
        gate_def={},
    ) is None


def test_enforce_session_verdict_canonical_with_zero_scores_when_llm_omits() -> None:
    """When the LLM emits session_summary but no session_verdict, the
    backstop produces a canonical shape with the four canonical dimension
    names and zero scores. weighted_score and passed are computed from
    the (zero) scores; passed=False under any non-zero threshold."""
    out = MockInterviewOutput(
        session_id=uuid.uuid4(),
        mode="system_design",
        turn_kind="session_summary",
        session_summary=SessionSummary(
            overall_score_0_to_100=70,
            headline="ok",
            strengths=[],
            weaknesses=[],
            suggested_next_action="next",
        ),
    )
    gate_def = {
        "found": True,
        "mock_interview_dimensions": {
            "clarity_of_questioning": 0.20,
            "directional_adherence": 0.30,
            "complexity_adaptation": 0.25,
            "technical_correctness": 0.25,
        },
        "mock_interview_pass_threshold": 0.75,
    }
    sv = _enforce_session_verdict(
        output=out,
        from_role_slug="ml_engineer",
        target_to_role="genai_engineer",
        gate_def=gate_def,
    )
    assert sv is not None
    names = {d.name for d in sv.dimension_scores}
    assert names == {
        "clarity_of_questioning",
        "directional_adherence",
        "complexity_adaptation",
        "technical_correctness",
    }
    weights_sum = sum(d.weight for d in sv.dimension_scores)
    assert abs(weights_sum - 1.0) < 1e-9
    assert sv.weighted_score == pytest.approx(0.0)
    assert sv.passed is False
    assert sv.transition_target.from_role_slug == "ml_engineer"
    assert sv.transition_target.to_role_slug == "genai_engineer"


def test_enforce_session_verdict_uses_llm_dimension_scores_when_present() -> None:
    out = MockInterviewOutput(
        session_id=uuid.uuid4(),
        mode="system_design",
        turn_kind="session_summary",
        session_summary=SessionSummary(
            overall_score_0_to_100=72,
            headline="ok",
            strengths=[],
            weaknesses=[],
            suggested_next_action="next",
        ),
        session_verdict=SessionVerdict(
            weighted_score=0.0,  # will be recomputed
            passed=False,
            dimension_scores=[
                MockInterviewDimensionScore(
                    name="clarity_of_questioning",
                    weight=0.0,  # backstop will overwrite from gate_def
                    score=0.8,
                    evidence="asked about latency budget on turn 1",
                ),
                MockInterviewDimensionScore(
                    name="directional_adherence",
                    weight=0.0,
                    score=0.7,
                    evidence="stayed on topic across the session",
                ),
                MockInterviewDimensionScore(
                    name="complexity_adaptation",
                    weight=0.0,
                    score=0.85,
                    evidence="adapted when scale constraint added",
                ),
                MockInterviewDimensionScore(
                    name="technical_correctness",
                    weight=0.0,
                    score=0.9,
                    evidence="precise on RAG architecture choices",
                ),
            ],
            transition_target=TransitionTarget(
                from_role_slug="ml_engineer",
                to_role_slug="genai_engineer",
            ),
        ),
    )
    gate_def = {
        "found": True,
        "mock_interview_dimensions": {
            "clarity_of_questioning": 0.20,
            "directional_adherence": 0.30,
            "complexity_adaptation": 0.25,
            "technical_correctness": 0.25,
        },
        "mock_interview_pass_threshold": 0.75,
    }
    sv = _enforce_session_verdict(
        output=out,
        from_role_slug="ml_engineer",
        target_to_role="genai_engineer",
        gate_def=gate_def,
    )
    assert sv is not None
    # Recomputed weighted_score = 0.20*0.8 + 0.30*0.7 + 0.25*0.85 +
    #                              0.25*0.9 = 0.16 + 0.21 + 0.2125 + 0.225 = 0.8075
    assert sv.weighted_score == pytest.approx(0.8075, abs=1e-6)
    assert sv.passed is True  # 0.8075 >= 0.75
    # Evidence strings preserved from the LLM's emission.
    by_name = {d.name: d for d in sv.dimension_scores}
    assert "latency budget" in by_name["clarity_of_questioning"].evidence
    assert "RAG architecture" in by_name["technical_correctness"].evidence


def test_practice_curator_output_unchanged_at_top_level() -> None:
    """The CP4 D-E coexistence change keeps PracticeCuratorOutput's top
    level identical — the source/curated_exercise_id additions live
    nested on Exercise. Pin this to catch silent schema-shape drift."""
    top_level_fields = set(PracticeCuratorOutput.model_fields.keys())
    assert top_level_fields == {
        "exercise",
        "starter_code",
        "expected_solution_shape",
        "evaluation_criteria",
        "hint_sequence",
        "estimated_time_minutes",
        "handoff_request",
    }
