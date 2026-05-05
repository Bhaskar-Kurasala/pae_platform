"""D11 Checkpoint 1 — SeniorEngineerOutput schema validation.

Pins the output schema's three-mode shape + the handoff_request
informational-only contract (D11 ships handoff_targets as Supervisor
metadata; D11 NEVER populates handoff_request — Option B per
docs/followups/handoff-protocol-d11-d13.md). The Checkpoint 4
unit-test file exercises the agent class itself; this file is a
schema-only fence so an accidental schema-shape change in CP2 trips
a clear test before the integration tests do.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.agents.senior_engineer import (
    CodeComment,
    SeniorEngineerOutput,
)
from app.schemas.supervisor import HandoffRequest


def test_pr_review_mode_shape_round_trip() -> None:
    out = SeniorEngineerOutput(
        mode="pr_review",
        verdict="request_changes",
        headline="Bare except hides the real bug",
        strengths=["Clear function names", "Type hints throughout"],
        comments=[
            CodeComment(
                line=17,
                severity="blocking",
                message="Bare `except:` swallows KeyboardInterrupt — narrow it.",
                suggested_change="except (ValueError, KeyError):",
            ),
            CodeComment(
                line=None,
                severity="suggestion",
                message="Consider extracting the parsing into a helper.",
            ),
        ],
        next_step="Fix the bare except and resubmit.",
        patterns_observed=["bare-except"],
    )
    j = out.model_dump_json()
    rebuilt = SeniorEngineerOutput.model_validate_json(j)
    assert rebuilt == out
    assert rebuilt.handoff_request is None  # Option B contract


def test_chat_help_mode_shape() -> None:
    out = SeniorEngineerOutput(
        mode="chat_help",
        explanation=(
            "Your loop terminates one iteration early because range(n) "
            "stops BEFORE n. If you want to include n, use range(n + 1)."
        ),
        code_suggestion="for i in range(n + 1):\n    ...",
    )
    assert out.mode == "chat_help"
    assert out.verdict is None
    assert out.score is None


def test_rubric_score_mode_shape() -> None:
    out = SeniorEngineerOutput(
        mode="rubric_score",
        score=82,
        dimension_scores={
            "correctness": 18,
            "readability": 16,
            "idiomatic": 14,
        },
        rubric_feedback="Strong correctness; idioms could be tighter.",
    )
    assert out.score == 82
    assert sum(out.dimension_scores.values()) <= out.score + 50  # sanity


def test_score_must_be_in_0_100_range() -> None:
    with pytest.raises(ValidationError):
        SeniorEngineerOutput(mode="rubric_score", score=120)
    with pytest.raises(ValidationError):
        SeniorEngineerOutput(mode="rubric_score", score=-5)


def test_strengths_max_three() -> None:
    """Pass 3c E2: strengths are 0-3 items. Pin via the pydantic max_length."""
    with pytest.raises(ValidationError):
        SeniorEngineerOutput(
            mode="pr_review",
            verdict="approve",
            strengths=["a", "b", "c", "d"],
        )


def test_handoff_request_field_present_but_default_none() -> None:
    """D11 ships handoff_request as Optional[HandoffRequest] = None.
    Schema shape is preserved for D13 to flip on without changing
    the contract."""
    out = SeniorEngineerOutput(mode="pr_review", verdict="approve")
    assert out.handoff_request is None

    # And populating it still validates — D13 path stays open.
    populated = SeniorEngineerOutput(
        mode="pr_review",
        verdict="comment",
        handoff_request=HandoffRequest(
            target_agent="learning_coach",
            reason="conceptual",
        ),
    )
    assert populated.handoff_request is not None
    assert populated.handoff_request.target_agent == "learning_coach"


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        SeniorEngineerOutput(mode="freeform")  # type: ignore[arg-type]


def test_extra_fields_rejected() -> None:
    """ConfigDict(extra='forbid') means typos at the LLM level fail
    fast rather than silently dropping signal."""
    with pytest.raises(ValidationError):
        SeniorEngineerOutput.model_validate(
            {
                "mode": "pr_review",
                "verdict": "approve",
                "definitive_score": 99,  # not in schema
            }
        )
