"""Pure-function tests for confidence calibration (P3 3A-7).

The DB-backed writer is trivial; these tests lock in:
  - the 1-5 validator boundary
  - the prompt overlay anchors so drift doesn't silently remove the
    "ask once per conversation" rule
"""

from __future__ import annotations

import pytest

from app.services.confidence_service import (
    CONFIDENCE_CALIBRATION_OVERLAY,
    VALID_VALUES,
    validate_value,
)


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_validate_value_accepts_in_range(value: int) -> None:
    assert validate_value(value) == value


@pytest.mark.parametrize("value", [0, -1, 6, 100, 10])
def test_validate_value_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValueError, match="1-5"):
        validate_value(value)


def test_valid_values_set_is_1_to_5() -> None:
    assert VALID_VALUES == frozenset({1, 2, 3, 4, 5})


def test_overlay_copy_anchors() -> None:
    # Drift guards — each of these phrases is load-bearing. If someone
    # edits the overlay, the rule should still:
    #   - specify a 1-5 scale
    #   - ask only once per conversation
    #   - skip trivial / debug turns
    text = CONFIDENCE_CALIBRATION_OVERLAY
    assert "1-5" in text
    assert "Only ask once" in text
    # Two common skip conditions.
    assert "error-paste" in text.lower() or "debug" in text.lower()
    assert "first two turns" in text.lower()
