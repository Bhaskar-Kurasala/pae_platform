"""Unit tests for the graded socratic overlay selector (P3 3A-3).

`_socratic_overlay_for` is a pure function — no DB, no LLM — so we can
assert the exact string chosen for each level. Keeps the graded behaviour
observable without having to stream through Claude.
"""

from __future__ import annotations

from app.api.v1.routes.stream import (
    _SOCRATIC_GENTLE_OVERLAY,
    _SOCRATIC_STANDARD_OVERLAY,
    _SOCRATIC_STRICT_OVERLAY,
    _socratic_overlay_for,
)


def test_level_zero_returns_none() -> None:
    assert _socratic_overlay_for(0) is None


def test_negative_level_returns_none() -> None:
    # Defensive clamp — should never be reached because Pydantic validates
    # the range, but if a bad row slips through we want "off" not a crash.
    assert _socratic_overlay_for(-1) is None


def test_level_one_is_gentle() -> None:
    assert _socratic_overlay_for(1) is _SOCRATIC_GENTLE_OVERLAY


def test_level_two_is_standard() -> None:
    assert _socratic_overlay_for(2) is _SOCRATIC_STANDARD_OVERLAY


def test_level_three_is_strict() -> None:
    assert _socratic_overlay_for(3) is _SOCRATIC_STRICT_OVERLAY


def test_level_above_three_falls_to_strict() -> None:
    # Same defensive floor-to-strict policy as tutor_mode_for_level.
    assert _socratic_overlay_for(99) is _SOCRATIC_STRICT_OVERLAY


def test_overlays_contain_level_cues() -> None:
    # Guard against copy drift: each overlay should name its level so the
    # model can tell them apart if the prompt starts getting combined.
    assert "GENTLE" in _SOCRATIC_GENTLE_OVERLAY
    assert "STANDARD" in _SOCRATIC_STANDARD_OVERLAY
    assert "STRICT" in _SOCRATIC_STRICT_OVERLAY
