"""JD parser tests — coercion logic + empty-input handling.

LLM-dependent paths are not exercised here; the orchestrator integration
test covers them with a mocked llm.
"""

from __future__ import annotations

from app.services.jd_parser import ParsedJd, _coerce_enum, _coerce_str_list, parse_jd
import pytest


def test_coerce_str_list_filters_non_strings_and_blanks() -> None:
    raw = ["python", "", None, 42, "  ", "fastapi"]
    out = _coerce_str_list(raw, max_len=5)
    assert out == ["python", "fastapi"]


def test_coerce_str_list_respects_max_len() -> None:
    raw = ["a", "b", "c", "d"]
    assert _coerce_str_list(raw, max_len=2) == ["a", "b"]


def test_coerce_str_list_handles_non_list() -> None:
    assert _coerce_str_list("not a list", max_len=3) == []
    assert _coerce_str_list(None, max_len=3) == []


def test_coerce_enum_accepts_known_values_lowercased() -> None:
    assert _coerce_enum("Junior", ("intern", "junior", "mid")) == "junior"
    assert _coerce_enum("STAFF", ("staff", "junior")) == "staff"


def test_coerce_enum_rejects_unknown_values() -> None:
    assert _coerce_enum("emperor", ("junior", "senior")) == "unspecified"
    assert _coerce_enum(None, ("junior", "senior")) == "unspecified"
    assert _coerce_enum(42, ("junior",)) == "unspecified"


def test_parsed_jd_to_dict_strips_runtime_metadata() -> None:
    jd = ParsedJd(
        role="Junior Python Dev",
        must_haves=["python"],
        input_tokens=123,
        output_tokens=45,
        model="claude-haiku-4-5",
    )
    d = jd.to_dict()
    assert "input_tokens" not in d
    assert "output_tokens" not in d
    assert "model" not in d
    assert d["role"] == "Junior Python Dev"
    assert d["must_haves"] == ["python"]


@pytest.mark.asyncio
async def test_parse_jd_empty_input_returns_empty_parse() -> None:
    result = await parse_jd("")
    assert isinstance(result, ParsedJd)
    assert result.role == ""
    assert result.must_haves == []
