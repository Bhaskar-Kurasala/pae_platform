"""Pure-helper tests for preferences service socratic mapping (P3 3A-3).

Covers the level↔tutor_mode projection without DB. The DB update path is
exercised by the existing `test_preferences_service.py` / endpoint tests.
"""

from __future__ import annotations

from app.services.preferences_service import (
    SOCRATIC_LEVEL_LABELS,
    level_from_tutor_mode,
    tutor_mode_for_level,
)


def test_tutor_mode_for_level_low_is_standard() -> None:
    assert tutor_mode_for_level(0) == "standard"
    assert tutor_mode_for_level(1) == "standard"
    assert tutor_mode_for_level(2) == "standard"


def test_tutor_mode_for_level_strict_at_three() -> None:
    assert tutor_mode_for_level(3) == "socratic_strict"


def test_tutor_mode_for_level_above_three_is_strict() -> None:
    # Defensive: if a future level=4 slips through validation, don't silently
    # downgrade to standard. Strict is the safer fall-through.
    assert tutor_mode_for_level(4) == "socratic_strict"


def test_level_from_tutor_mode_roundtrips_strict() -> None:
    assert level_from_tutor_mode("socratic_strict") == 3


def test_level_from_tutor_mode_standard_is_zero() -> None:
    assert level_from_tutor_mode("standard") == 0


def test_level_from_tutor_mode_unknown_defaults_to_zero() -> None:
    assert level_from_tutor_mode("anything_else") == 0


def test_level_labels_cover_full_range() -> None:
    # The slider UI and telemetry both depend on these four labels existing.
    assert set(SOCRATIC_LEVEL_LABELS.keys()) == {0, 1, 2, 3}
    assert SOCRATIC_LEVEL_LABELS[0] == "off"
    assert SOCRATIC_LEVEL_LABELS[3] == "strict"
