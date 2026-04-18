"""Unit tests for SM-2 math (P2-05).

We test `apply_sm2` in isolation — no DB. The algorithm is deterministic, so
every case has a single correct output and we can pin exact numbers.
"""

from __future__ import annotations

from app.services.srs_service import (
    DEFAULT_EASE,
    MAX_EASE,
    MIN_EASE,
    apply_sm2,
)


def test_first_correct_review_advances_to_one_day() -> None:
    r = apply_sm2(quality=5, ease_factor=DEFAULT_EASE, interval_days=0, repetitions=0)
    assert r.interval_days == 1
    assert r.repetitions == 1
    assert r.ease_factor >= DEFAULT_EASE  # q=5 bumps ease


def test_second_correct_review_advances_to_six_days() -> None:
    r = apply_sm2(quality=4, ease_factor=DEFAULT_EASE, interval_days=1, repetitions=1)
    assert r.interval_days == 6
    assert r.repetitions == 2


def test_third_correct_review_multiplies_by_ease() -> None:
    # With ease=2.5, interval 6 * 2.5 = 15
    r = apply_sm2(quality=4, ease_factor=2.5, interval_days=6, repetitions=2)
    assert r.interval_days == 15
    assert r.repetitions == 3


def test_wrong_answer_resets_repetitions_and_interval() -> None:
    r = apply_sm2(quality=1, ease_factor=2.5, interval_days=15, repetitions=4)
    assert r.interval_days == 1
    assert r.repetitions == 0
    # Ease still drops on failure
    assert r.ease_factor < 2.5


def test_ease_is_clamped_to_minimum() -> None:
    # Repeated failures should floor at MIN_EASE, not go below.
    ef = DEFAULT_EASE
    for _ in range(30):
        r = apply_sm2(quality=0, ease_factor=ef, interval_days=1, repetitions=0)
        ef = r.ease_factor
    assert ef == MIN_EASE


def test_ease_is_clamped_to_maximum() -> None:
    ef = DEFAULT_EASE
    for _ in range(30):
        r = apply_sm2(quality=5, ease_factor=ef, interval_days=1, repetitions=5)
        ef = r.ease_factor
    assert ef <= MAX_EASE


def test_quality_three_is_boundary_correct() -> None:
    # q=3 must count as correct (interval advances, repetitions increment),
    # even though it's the "hard" end. This is how SM-2 differs from naive
    # right/wrong: a shaky-but-right answer still moves forward, just slower.
    r = apply_sm2(quality=3, ease_factor=DEFAULT_EASE, interval_days=6, repetitions=2)
    assert r.repetitions == 3
    assert r.interval_days > 1


def test_quality_out_of_range_is_clamped() -> None:
    # SM-2 only defines 0..5. A -1 or 99 should not blow up.
    low = apply_sm2(quality=-1, ease_factor=2.5, interval_days=5, repetitions=3)
    high = apply_sm2(quality=99, ease_factor=2.5, interval_days=5, repetitions=3)
    assert low.interval_days == 1  # treated as failure
    assert high.repetitions == 4  # treated as perfect
