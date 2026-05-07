"""D13.5 Stage 1 — capability extensions for mandatory validation chains.

Pins:
  • AgentCapability accepts requires_mandatory_validation_by +
    validation_input_adapter with default None
  • tailored_resume's capability declares both fields populated
  • Adapter produces a valid ResumeReviewerInput from a representative
    TailoredResumeOutput
  • Other agents' capabilities have both fields as None (no accidental opt-in)
  • Capability still serializes via model_dump (with the adapter excluded)

Pure schema/function tests, no LLM cost.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.adapters.tailored_to_reviewer import (
    tailored_resume_to_reviewer_input,
)
from app.agents.capability import list_capabilities
from app.agents.resume_reviewer_v2 import ResumeReviewerInput
from app.schemas.agents.tailored_resume import ResumeChange, TailoredResumeOutput
from app.schemas.supervisor import AgentCapability


# ── AgentCapability schema tests ────────────────────────────────────


def test_capability_accepts_new_fields_with_defaults() -> None:
    """Bare-minimum capability instantiation works with defaults."""
    cap = AgentCapability(name="x", description="x")
    assert cap.requires_mandatory_validation_by is None
    assert cap.validation_input_adapter is None


def test_capability_accepts_callable_adapter() -> None:
    """Adapter field accepts a Callable thanks to arbitrary_types_allowed."""

    def _identity(x: object) -> object:
        return x

    cap = AgentCapability(
        name="x",
        description="x",
        requires_mandatory_validation_by="some_validator",
        validation_input_adapter=_identity,
    )
    assert cap.requires_mandatory_validation_by == "some_validator"
    assert cap.validation_input_adapter is _identity


# ── Registry checks ─────────────────────────────────────────────────


def _get_cap(name: str) -> AgentCapability:
    cap = next((c for c in list_capabilities() if c.name == name), None)
    assert cap is not None, f"capability {name!r} not found"
    return cap


def test_tailored_resume_declares_mandatory_validation() -> None:
    """tailored_resume's capability is the canonical D13.5 example."""
    cap = _get_cap("tailored_resume")
    assert cap.requires_mandatory_validation_by == "resume_reviewer"
    assert cap.validation_input_adapter is not None
    # The wired adapter is the canonical one.
    assert cap.validation_input_adapter is tailored_resume_to_reviewer_input


def test_other_agents_have_no_mandatory_validation() -> None:
    """No accidental opt-ins: every other capability leaves both fields None."""
    for cap in list_capabilities():
        if cap.name == "tailored_resume":
            continue
        assert cap.requires_mandatory_validation_by is None, (
            f"{cap.name!r} unexpectedly declared mandatory validation"
        )
        assert cap.validation_input_adapter is None, (
            f"{cap.name!r} unexpectedly carries a validation adapter"
        )


# ── Adapter behaviour ───────────────────────────────────────────────


def _make_tailored_output(
    *,
    resume_text: str = "Tailored resume body...",
    keyword_alignment_score: float = 0.85,
) -> TailoredResumeOutput:
    return TailoredResumeOutput(
        tailored_resume=resume_text,
        changes_made=[
            ResumeChange(
                section="Experience",
                what_changed="Reordered bullet points",
                why="Match JD priority on retrieval systems",
            ),
        ],
        keyword_alignment_score=keyword_alignment_score,
        unsupported_additions=[],
        ats_compatibility_notes=["Use standard fonts"],
        handoff_request=None,
    )


def test_adapter_produces_valid_reviewer_input() -> None:
    """Pydantic accepts the adapter's output as a ResumeReviewerInput."""
    out = _make_tailored_output()
    reviewer_input = tailored_resume_to_reviewer_input(out)
    assert isinstance(reviewer_input, ResumeReviewerInput)
    assert reviewer_input.resume_text == out.tailored_resume


def test_adapter_threads_validation_concerns() -> None:
    """The adapter scopes the validator to the mandatory-validation
    contract via specific_concerns."""
    reviewer_input = tailored_resume_to_reviewer_input(_make_tailored_output())
    assert "unsupported_claims" in reviewer_input.specific_concerns
    assert "ats_compatibility" in reviewer_input.specific_concerns


def test_adapter_resolves_resume_text_through_synonym_path() -> None:
    """The validator's resolved_resume_text() picks up resume_text first
    even though question/task/user_message are also fields. Sanity check
    that nothing in the adapter accidentally puts the body in a synonym
    field."""
    reviewer_input = tailored_resume_to_reviewer_input(
        _make_tailored_output(resume_text="The actual tailored resume body.")
    )
    assert reviewer_input.resolved_resume_text() == (
        "The actual tailored resume body."
    )


def test_adapter_handles_empty_resume_string() -> None:
    """Edge: an empty tailored_resume still produces a valid input
    (the validator will surface the absence as a finding)."""
    out = TailoredResumeOutput(
        tailored_resume="",
        keyword_alignment_score=0.0,
    )
    reviewer_input = tailored_resume_to_reviewer_input(out)
    # Empty string is allowed by the schema (no min_length).
    assert reviewer_input.resume_text == ""


def test_adapter_accepts_dict_input() -> None:
    """The adapter accepts a dict (production path: call_agent returns
    output as `model_dump(mode='json')`, not a Pydantic instance)."""
    output_dict = {
        "tailored_resume": "Resume body from dict.",
        "changes_made": [],
        "keyword_alignment_score": 0.7,
        "unsupported_additions": [],
        "ats_compatibility_notes": [],
        "handoff_request": None,
    }
    reviewer_input = tailored_resume_to_reviewer_input(output_dict)
    assert reviewer_input.resume_text == "Resume body from dict."
    assert "unsupported_claims" in reviewer_input.specific_concerns


def test_adapter_rejects_non_dict_non_model_input() -> None:
    """Defensive: anything that's neither a TailoredResumeOutput nor a
    dict raises TypeError. Catches accidental misuse early."""
    with pytest.raises(TypeError):
        tailored_resume_to_reviewer_input("not a valid shape")  # type: ignore[arg-type]


def test_adapter_rejects_dict_with_wrong_typed_field() -> None:
    """Defensive: a dict with the right key but wrong type raises
    ValueError so the dispatch layer's adapter-error path triggers
    fail-loud behavior rather than passing junk through."""
    bad_dict = {"tailored_resume": 12345}  # not a string
    with pytest.raises(ValueError):
        tailored_resume_to_reviewer_input(bad_dict)


# ── Serialization sanity ────────────────────────────────────────────


def test_capability_dump_excludes_adapter_cleanly() -> None:
    """If a future code path needs to serialize capabilities, the
    Callable can be excluded without error. Not currently exercised
    in production paths, but pinned so future serializers don't trip."""
    cap = _get_cap("tailored_resume")
    dumped = cap.model_dump(exclude={"validation_input_adapter"})
    assert "validation_input_adapter" not in dumped
    assert dumped["requires_mandatory_validation_by"] == "resume_reviewer"
    assert dumped["name"] == "tailored_resume"
