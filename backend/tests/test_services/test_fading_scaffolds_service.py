"""Pure tests for 3B #92 fading-scaffolds helpers."""

from __future__ import annotations

from app.services.fading_scaffolds_service import (
    allowed_hint_count,
    fade_scaffolds,
)


def test_first_attempt_gets_all_three_levels() -> None:
    assert allowed_hint_count(1) == 3


def test_second_attempt_loses_one_level() -> None:
    assert allowed_hint_count(2) == 2


def test_third_attempt_keeps_only_gentle_nudge() -> None:
    assert allowed_hint_count(3) == 1


def test_fourth_attempt_fades_to_zero() -> None:
    assert allowed_hint_count(4) == 0


def test_fifth_attempt_stays_at_zero() -> None:
    assert allowed_hint_count(5) == 0


def test_zero_or_negative_gets_all_levels_as_fallback() -> None:
    assert allowed_hint_count(0) == 3
    assert allowed_hint_count(-1) == 3


def test_fade_first_attempt_full_envelope() -> None:
    env = fade_scaffolds(1)
    assert env.allowed_levels == ("gentle_nudge", "worked_sub_step", "near_solution")
    assert env.faded is False


def test_fade_second_attempt_drops_near_solution() -> None:
    env = fade_scaffolds(2)
    assert env.allowed_levels == ("gentle_nudge", "worked_sub_step")
    assert env.faded is True
    assert "fading" in env.reason


def test_fade_third_attempt_keeps_only_nudge() -> None:
    env = fade_scaffolds(3)
    assert env.allowed_levels == ("gentle_nudge",)
    assert "1 level" in env.reason


def test_fade_fourth_attempt_empty_envelope() -> None:
    env = fade_scaffolds(4)
    assert env.allowed_levels == ()
    assert "retrieval" in env.reason


def test_fade_normalizes_zero_attempt_to_one() -> None:
    env = fade_scaffolds(0)
    assert env.attempt_number == 1
