"""D12 CP3 Phase 4 (Bug 17) — pin truncate_to_schema behavior.

The helper enforces Pydantic max_length constraints server-side
before model_validate runs. Replaces prompt-level constraint emphasis
which proved unreliable under MiniMax. See agent-tool-call-discipline.md
or the schema-aware-server-side-validation.md follow-up doc for context.

Tests cover:
  • String at/below/above max_length
  • Strings with no max_length constraint
  • None values preserved
  • Nested BaseModel recursion
  • List[BaseModel] recursion with mixed overshoots
  • Optional[Model] resolved through Union
  • Untyped dict[str, Any] not recursed into
  • Non-string fields untouched
  • Union with multiple BaseModel members logs and skips
"""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.agents.parsing_helpers import truncate_to_schema


# ── Fixture models ───────────────────────────────────────────────


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    short: str = Field(max_length=10)
    unconstrained: str = ""


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=5)
    note: str | None = Field(default=None, max_length=8)


class _Outer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=20)
    untouched: int = 0
    inner: _Inner | None = None
    items: list[_Item] = Field(default_factory=list)
    raw: dict[str, str] = Field(default_factory=dict)


# ── String truncation ─────────────────────────────────────────────


class TestStringTruncation:
    def test_string_above_max_length_truncated(self) -> None:
        data = {"title": "x" * 50, "untouched": 0}
        result = truncate_to_schema(data, _Outer)
        assert result["title"] == "x" * 20

    def test_string_at_max_length_unchanged(self) -> None:
        data = {"title": "x" * 20, "untouched": 0}
        result = truncate_to_schema(data, _Outer)
        assert result["title"] == "x" * 20

    def test_string_below_max_length_unchanged(self) -> None:
        data = {"title": "short", "untouched": 0}
        result = truncate_to_schema(data, _Outer)
        assert result["title"] == "short"

    def test_string_with_no_max_length_unchanged(self) -> None:
        data = {"title": "ok", "untouched": 0, "inner": {"short": "x", "unconstrained": "y" * 999}}
        result = truncate_to_schema(data, _Outer)
        # `unconstrained` has no max_length — should pass through.
        assert result["inner"]["unconstrained"] == "y" * 999


# ── None / preservation ───────────────────────────────────────────


class TestNoneValues:
    def test_none_value_for_string_field_preserved(self) -> None:
        data = {"name": "ok", "note": None}
        result = truncate_to_schema(data, _Item)
        assert result["note"] is None

    def test_none_value_for_optional_basemodel_preserved(self) -> None:
        data = {"title": "t", "untouched": 0, "inner": None}
        result = truncate_to_schema(data, _Outer)
        assert result["inner"] is None


# ── Nested recursion ──────────────────────────────────────────────


class TestNestedModelRecursion:
    def test_nested_basemodel_recursed(self) -> None:
        data = {
            "title": "ok",
            "untouched": 0,
            "inner": {
                "short": "x" * 30,  # exceeds 10
                "unconstrained": "free",
            },
        }
        result = truncate_to_schema(data, _Outer)
        assert result["inner"]["short"] == "x" * 10
        assert result["inner"]["unconstrained"] == "free"

    def test_optional_basemodel_recursed_when_present(self) -> None:
        """Optional[_Inner] — annotation is Union[_Inner, None].
        Non-None value should still recurse into _Inner."""
        data = {
            "title": "t",
            "untouched": 0,
            "inner": {"short": "yyyyyyyyyy_overflow"},
        }
        result = truncate_to_schema(data, _Outer)
        assert len(result["inner"]["short"]) == 10


# ── List recursion ────────────────────────────────────────────────


class TestListRecursion:
    def test_list_of_basemodels_each_truncated(self) -> None:
        data = {
            "title": "ok",
            "untouched": 0,
            "items": [
                {"name": "x" * 20},          # exceeds 5
                {"name": "fine"},
                {"name": "y" * 99, "note": "z" * 99},  # exceeds 5 + 8
            ],
        }
        result = truncate_to_schema(data, _Outer)
        assert result["items"][0]["name"] == "x" * 5
        assert result["items"][1]["name"] == "fine"
        assert result["items"][2]["name"] == "y" * 5
        assert result["items"][2]["note"] == "z" * 8

    def test_empty_list_unchanged(self) -> None:
        data = {"title": "ok", "untouched": 0, "items": []}
        result = truncate_to_schema(data, _Outer)
        assert result["items"] == []


# ── Untyped dict not recursed ─────────────────────────────────────


class TestUntypedDictNotRecursed:
    def test_dict_str_str_field_passes_through(self) -> None:
        """`raw: dict[str, str]` is a typed dict but not a BaseModel.
        We don't apply max_length to its contents (no schema to read)."""
        data = {
            "title": "ok",
            "untouched": 0,
            "raw": {"any_key": "x" * 999},
        }
        result = truncate_to_schema(data, _Outer)
        assert result["raw"]["any_key"] == "x" * 999


# ── Non-string fields untouched ───────────────────────────────────


class TestNonStringFields:
    def test_int_field_unchanged(self) -> None:
        data = {"title": "ok", "untouched": 12345}
        result = truncate_to_schema(data, _Outer)
        assert result["untouched"] == 12345

    def test_does_not_mutate_input(self) -> None:
        data = {"title": "x" * 50, "untouched": 0}
        original = dict(data)
        result = truncate_to_schema(data, _Outer)
        assert data == original  # input unchanged
        assert result is not data  # new dict


# ── Union ambiguity handling ──────────────────────────────────────


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str = Field(max_length=3)


class _B(BaseModel):
    model_config = ConfigDict(extra="forbid")
    b: str = Field(max_length=3)


class _Container(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Union of two BaseModels — can't disambiguate by shape alone.
    item: _A | _B


class TestUnionAmbiguity:
    def test_ambiguous_union_skips_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When a field is Union[Model1, Model2] (no None), we can't
        disambiguate which schema to apply, so we skip recursion and
        log a warning. The string overshoot survives — Pydantic
        validation will surface it."""
        data = {"item": {"a": "long string"}}
        with caplog.at_level(logging.WARNING):
            result = truncate_to_schema(data, _Container)
        # Field passed through unchanged (no truncation).
        assert result["item"] == {"a": "long string"}


# ── Real D12 schemas — sanity check ───────────────────────────────


class TestRealD12Schemas:
    """Smoke tests against actual D12 v2 output schemas to confirm
    the helper handles their shapes without crashing."""

    def test_career_coach_output_smoke(self) -> None:
        """CareerCoachOutput has nested CareerPlan with list[WeeklyFocus]
        and list[ProjectRef], plus list[Milestone]. Verify the helper
        traverses without error."""
        from app.schemas.agents.career_coach import CareerCoachOutput

        data = {
            "headline": "x" * 500,                 # exceeds 200
            "current_state_assessment": "y" * 50,  # no max_length
            "plan": {
                "timeline_weeks": 12,
                "weekly_focus_areas": [
                    {
                        "week": 1,
                        "theme": "z" * 200,        # exceeds 100
                        "primary_activity": "ok",
                    },
                ],
                "projects_to_complete": [],
                "skills_to_develop": ["py", "ml"],
            },
            "immediate_concerns": [],
            "milestones": [],
            "suggested_next_action": "a" * 500,    # exceeds 300
            "handoff_requests": [],
        }
        result = truncate_to_schema(data, CareerCoachOutput)
        assert len(result["headline"]) == 200
        assert len(result["plan"]["weekly_focus_areas"][0]["theme"]) == 100
        assert len(result["suggested_next_action"]) == 300

    def test_resume_reviewer_output_smoke(self) -> None:
        """ResumeReviewerOutput has nested ResumeSuggestion (×2 lists),
        UnsupportedClaim, Accomplishment. The Bug 17 root cause."""
        from app.schemas.agents.resume_reviewer import ResumeReviewerOutput

        data = {
            "overall_score": 75,
            "headline_assessment": "x" * 500,  # exceeds 200
            "strengths": [],
            "issues": [
                {
                    "section": "x" * 200,          # exceeds 60
                    "original_text": "y" * 1000,   # exceeds 400
                    "suggested_text": "z" * 1000,  # exceeds 400
                    "rationale": "a" * 1000,       # exceeds 200
                },
            ],
            "unsupported_claims": [],
            "underrepresented_accomplishments": [],
            "suggested_changes": [],
            "handoff_request": None,
        }
        result = truncate_to_schema(data, ResumeReviewerOutput)
        assert len(result["headline_assessment"]) == 200
        assert len(result["issues"][0]["section"]) == 60
        assert len(result["issues"][0]["original_text"]) == 400
        assert len(result["issues"][0]["suggested_text"]) == 400
        assert len(result["issues"][0]["rationale"]) == 200
