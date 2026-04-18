"""Pure tests for the self-explanation normalizer (P3 3A-9)."""

from __future__ import annotations

from app.services.exercise_service import _normalize_self_explanation


def test_none_passes_through() -> None:
    assert _normalize_self_explanation(None) is None


def test_empty_string_becomes_none() -> None:
    assert _normalize_self_explanation("") is None


def test_whitespace_only_becomes_none() -> None:
    assert _normalize_self_explanation("   \n\t  ") is None


def test_too_short_becomes_none() -> None:
    # "ok" is 2 chars — below the 3-char minimum; counts as a skip.
    assert _normalize_self_explanation("ok") is None


def test_minimum_accepted_length_survives() -> None:
    assert _normalize_self_explanation("abc") == "abc"


def test_surrounding_whitespace_stripped() -> None:
    assert _normalize_self_explanation("  sorts in place  ") == "sorts in place"


def test_realistic_one_sentence_survives() -> None:
    text = (
        "Because binary search halves the range each step, so log2(n) "
        "comparisons for n=10M is ~23."
    )
    assert _normalize_self_explanation(text) == text
