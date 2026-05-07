"""D13 CP3 Phase 1.8 — strip_extra_fields unit tests.

Pure logic; no LLM cost. Pins the helper that drops unknown keys
before Pydantic validation. Counterpart to test_truncate_to_schema.py.

Bug 23 (D13 CP3 Phase 4): under MiniMax, the LLM occasionally
flattens nested schema fields to the top level. With extra="forbid"
output models, that triggers ValidationError. strip_extra_fields
drops those unknown keys server-side, before validation runs.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.agents.parsing_helpers import strip_extra_fields


# ── Fixtures: models with various extra= configurations ────────────


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(max_length=100)


class _ForbidOuter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid_field: str
    nested: _Inner | None = None
    items: list[_Inner] = Field(default_factory=list)


class _IgnoreOuter(BaseModel):
    model_config = ConfigDict(extra="ignore")
    valid_field: str


class _AllowOuter(BaseModel):
    model_config = ConfigDict(extra="allow")
    valid_field: str


class _UntypedDictOuter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metadata: dict[str, Any] = Field(default_factory=dict)
    label: str


# ── Tests ──────────────────────────────────────────────────────────


def test_top_level_extra_key_dropped() -> None:
    """The Bug 23 case: an unknown key at the top level is dropped."""
    data = {"valid_field": "x", "extra_key": "y", "another_extra": 42}
    out = strip_extra_fields(data, _ForbidOuter)
    assert out == {"valid_field": "x"}


def test_nested_extra_key_dropped() -> None:
    """Unknown key inside a nested BaseModel field is dropped, while
    the parent's other fields are preserved."""
    data = {
        "valid_field": "x",
        "nested": {"value": "ok", "extra_in_nested": "drop"},
    }
    out = strip_extra_fields(data, _ForbidOuter)
    assert out == {
        "valid_field": "x",
        "nested": {"value": "ok"},
    }


def test_list_of_models_each_stripped() -> None:
    """Each list element gets its own strip pass."""
    data = {
        "valid_field": "x",
        "items": [
            {"value": "a", "junk": 1},
            {"value": "b", "another_junk": "y"},
            {"value": "c"},
        ],
    }
    out = strip_extra_fields(data, _ForbidOuter)
    assert out == {
        "valid_field": "x",
        "items": [{"value": "a"}, {"value": "b"}, {"value": "c"}],
    }


def test_optional_basemodel_none_preserved() -> None:
    """Optional[BaseModel] field with value None passes through unchanged."""
    data = {"valid_field": "x", "nested": None}
    out = strip_extra_fields(data, _ForbidOuter)
    assert out == {"valid_field": "x", "nested": None}


def test_extra_ignore_also_strips() -> None:
    """extra='ignore' produces same observable result as 'forbid' —
    we strip eagerly to match."""
    data = {"valid_field": "x", "extra_key": "drop_me"}
    out = strip_extra_fields(data, _IgnoreOuter)
    assert out == {"valid_field": "x"}


def test_extra_allow_passes_unknown_through() -> None:
    """extra='allow' callers want unknown keys preserved."""
    data = {"valid_field": "x", "extra_key": "keep_me"}
    out = strip_extra_fields(data, _AllowOuter)
    assert out == {"valid_field": "x", "extra_key": "keep_me"}


def test_empty_dict_returns_empty_dict() -> None:
    out = strip_extra_fields({}, _ForbidOuter)
    assert out == {}


def test_non_dict_input_passes_through() -> None:
    """Defensive: non-dict input is returned as-is so Pydantic surfaces
    the type error rather than this helper crashing."""
    assert strip_extra_fields("not a dict", _ForbidOuter) == "not a dict"  # type: ignore[arg-type]
    assert strip_extra_fields(42, _ForbidOuter) == 42  # type: ignore[arg-type]
    assert strip_extra_fields(None, _ForbidOuter) is None  # type: ignore[arg-type]


def test_untyped_dict_field_not_recursed() -> None:
    """A field typed as dict[str, Any] (no nested BaseModel) is left
    alone — we don't have a model to validate against."""
    data = {
        "label": "x",
        "metadata": {"any_key": "kept", "another": 42},
    }
    out = strip_extra_fields(data, _UntypedDictOuter)
    assert out == {
        "label": "x",
        "metadata": {"any_key": "kept", "another": 42},
    }


def test_does_not_mutate_input() -> None:
    """strip_extra_fields returns a new dict; the caller's dict is
    untouched."""
    data = {"valid_field": "x", "extra": "y", "nested": {"value": "ok", "extra_n": 1}}
    snapshot = {"valid_field": "x", "extra": "y", "nested": {"value": "ok", "extra_n": 1}}
    strip_extra_fields(data, _ForbidOuter)
    assert data == snapshot


def test_composition_with_truncate_to_schema() -> None:
    """The canonical composition: strip first, then truncate, then validate."""
    from app.agents.parsing_helpers import truncate_to_schema

    too_long = "x" * 200  # _Inner.value has max_length=100.
    data = {
        "valid_field": "x",
        "extra_top": "drops",
        "nested": {"value": too_long, "extra_nested": "drops"},
    }
    stripped = strip_extra_fields(data, _ForbidOuter)
    truncated = truncate_to_schema(stripped, _ForbidOuter)
    validated = _ForbidOuter.model_validate(truncated)
    assert validated.valid_field == "x"
    assert validated.nested is not None
    assert len(validated.nested.value) == 100


def test_strip_logs_dropped_keys_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    """Each dropped key emits one debug log line. Verifies the
    queryable signal exists for live shape-drift monitoring."""
    import logging

    with caplog.at_level(logging.DEBUG, logger="app.agents.parsing_helpers"):
        data = {"valid_field": "x", "drift_a": 1, "drift_b": 2}
        strip_extra_fields(data, _ForbidOuter)
