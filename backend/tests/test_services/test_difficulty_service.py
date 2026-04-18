"""Pure tests for 3B #90 desirable-difficulty helpers."""

from __future__ import annotations

from uuid import uuid4

from app.services.difficulty_service import (
    FirstTryOutcome,
    next_difficulty,
    prev_difficulty,
    recommend_difficulty,
)


def _o(passed: bool, attempts: int = 1) -> FirstTryOutcome:
    return FirstTryOutcome(
        exercise_id=uuid4(), passed_first_try=passed, attempts=attempts
    )


def test_next_difficulty_walks_up() -> None:
    assert next_difficulty("easy") == "medium"
    assert next_difficulty("medium") == "hard"


def test_next_difficulty_clamps_at_top() -> None:
    assert next_difficulty("hard") == "hard"


def test_next_difficulty_unknown_passthrough() -> None:
    assert next_difficulty("impossible") == "impossible"


def test_prev_difficulty_walks_down() -> None:
    assert prev_difficulty("hard") == "medium"
    assert prev_difficulty("medium") == "easy"


def test_prev_difficulty_clamps_at_bottom() -> None:
    assert prev_difficulty("easy") == "easy"


def test_recommend_bumps_up_after_three_first_try_passes() -> None:
    rec = recommend_difficulty(
        "medium", [_o(True), _o(True), _o(True)]
    )
    assert rec.recommended == "hard"
    assert "harder" in rec.reason


def test_recommend_does_not_bump_past_hard() -> None:
    rec = recommend_difficulty(
        "hard", [_o(True), _o(True), _o(True)]
    )
    assert rec.recommended == "hard"


def test_recommend_holds_when_fewer_than_three_samples() -> None:
    rec = recommend_difficulty("medium", [_o(True), _o(True)])
    assert rec.recommended == "medium"


def test_recommend_eases_down_on_two_failures() -> None:
    rec = recommend_difficulty(
        "medium", [_o(False), _o(True), _o(False)]
    )
    assert rec.recommended == "easy"


def test_recommend_does_not_ease_past_easy() -> None:
    rec = recommend_difficulty(
        "easy", [_o(False), _o(False)]
    )
    assert rec.recommended == "easy"


def test_recommend_holds_on_single_failure() -> None:
    rec = recommend_difficulty(
        "medium", [_o(True), _o(False), _o(True)]
    )
    assert rec.recommended == "medium"


def test_recommend_unknown_difficulty_passes_through() -> None:
    rec = recommend_difficulty("impossible", [_o(True), _o(True), _o(True)])
    assert rec.recommended == "impossible"


def test_recommend_bump_beats_ease_when_window_is_all_pass() -> None:
    # Most-recent 3 all pass (bump), but deeper history has failures.
    # Window check should win and bump up.
    rec = recommend_difficulty(
        "medium",
        [_o(True), _o(True), _o(True), _o(False), _o(False)],
    )
    assert rec.recommended == "hard"
