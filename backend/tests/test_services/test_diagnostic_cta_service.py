"""Pure tests for 3B #4 diagnostic CTA normalization."""

from __future__ import annotations

import pytest

from app.services.diagnostic_cta_service import normalize_decision


def test_accepts_canonical_values() -> None:
    assert normalize_decision("opted_in") == "opted_in"
    assert normalize_decision("dismissed") == "dismissed"
    assert normalize_decision("snoozed") == "snoozed"


def test_strips_whitespace() -> None:
    assert normalize_decision("  opted_in  ") == "opted_in"


def test_lowercases_input() -> None:
    assert normalize_decision("DISMISSED") == "dismissed"
    assert normalize_decision("Snoozed") == "snoozed"


def test_accepts_hyphenated_form() -> None:
    assert normalize_decision("opted-in") == "opted_in"


def test_accepts_spaced_form() -> None:
    assert normalize_decision("opted in") == "opted_in"


def test_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        normalize_decision("maybe")


def test_rejects_empty_string() -> None:
    with pytest.raises(ValueError):
        normalize_decision("")


def test_rejects_none_via_empty_coerce() -> None:
    # normalize_decision receives str but defensive "or ''" path is covered.
    with pytest.raises(ValueError):
        normalize_decision(None)  # type: ignore[arg-type]
