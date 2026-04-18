"""Tests for the senior-engineer review agent (P2-04).

We don't hit the LLM — we exercise the sanitizer / extractor so that weird
model output doesn't crash the endpoint.
"""

from __future__ import annotations

import pytest

from app.agents.senior_engineer import (
    _clean_text_blocks,
    _extract_json,
    _sanitize_review,
)


def test_extract_json_from_fenced_block() -> None:
    raw = 'Here is the review:\n```json\n{"verdict":"approve","next_step":"ship it"}\n```\nDone.'
    result = _extract_json(raw)
    assert result["verdict"] == "approve"


def test_extract_json_from_plain_object() -> None:
    raw = 'Prose before.\n{"verdict":"comment","comments":[]}\nMore prose.'
    result = _extract_json(raw)
    assert result["verdict"] == "comment"


def test_extract_json_returns_empty_on_garbage() -> None:
    assert _extract_json("no json at all here") == {}


def test_clean_text_blocks_handles_extended_thinking() -> None:
    raw = [
        {"type": "thinking", "thinking": "let me think"},
        {"type": "text", "text": "real output"},
    ]
    assert _clean_text_blocks(raw) == "real output"


def test_sanitize_coerces_unknown_verdict_to_comment() -> None:
    out = _sanitize_review({"verdict": "lgtm", "comments": []})
    assert out["verdict"] == "comment"


def test_sanitize_promotes_to_request_changes_when_blocking_present() -> None:
    out = _sanitize_review(
        {
            "verdict": "approve",
            "comments": [
                {"line": 3, "severity": "blocking", "message": "syntax error"}
            ],
        }
    )
    assert out["verdict"] == "request_changes"


def test_sanitize_downgrades_request_changes_without_blocking() -> None:
    out = _sanitize_review(
        {
            "verdict": "request_changes",
            "comments": [
                {"line": 2, "severity": "suggestion", "message": "rename var"}
            ],
        }
    )
    assert out["verdict"] == "comment"


def test_sanitize_clamps_line_and_severity() -> None:
    out = _sanitize_review(
        {
            "verdict": "comment",
            "comments": [
                {"line": -5, "severity": "catastrophic", "message": "m"},
                {"line": "seven", "severity": "nit", "message": "ok"},
            ],
        }
    )
    assert out["comments"][0]["line"] == 1
    assert out["comments"][0]["severity"] == "suggestion"  # unknown → suggestion
    assert out["comments"][1]["line"] == 1
    assert out["comments"][1]["severity"] == "nit"


def test_sanitize_drops_comments_without_message() -> None:
    out = _sanitize_review(
        {
            "verdict": "comment",
            "comments": [
                {"line": 1, "severity": "nit", "message": ""},
                {"line": 2, "severity": "nit", "message": "keep me"},
            ],
        }
    )
    assert len(out["comments"]) == 1
    assert out["comments"][0]["message"] == "keep me"


def test_sanitize_truncates_long_strings() -> None:
    out = _sanitize_review(
        {
            "verdict": "comment",
            "headline": "x" * 500,
            "comments": [{"line": 1, "severity": "nit", "message": "y" * 1000}],
            "next_step": "z" * 1000,
        }
    )
    assert len(out["headline"]) <= 240
    assert len(out["comments"][0]["message"]) <= 500
    assert len(out["next_step"]) <= 400


def test_sanitize_caps_strengths_at_three() -> None:
    out = _sanitize_review({"verdict": "approve", "strengths": ["a", "b", "c", "d", "e"]})
    assert len(out["strengths"]) == 3


def test_sanitize_supplies_defaults_for_minimal_input() -> None:
    out = _sanitize_review({})
    assert out["verdict"] == "comment"
    assert out["headline"]
    assert out["next_step"]
    assert out["strengths"] == []
    assert out["comments"] == []
