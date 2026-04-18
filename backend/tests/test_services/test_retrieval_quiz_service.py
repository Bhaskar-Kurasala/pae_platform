"""Pure tests for the retrieval-quiz ranker + EMA (P3 3A-10)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.services.retrieval_quiz_service import pick_mcqs, update_confidence_ema


@dataclass
class _MCQ:
    id: uuid.UUID
    lesson_id: uuid.UUID | None
    question: str
    options: dict[str, Any]


def _mcq(lesson_id: uuid.UUID | None) -> _MCQ:
    return _MCQ(
        id=uuid.uuid4(),
        lesson_id=lesson_id,
        question="q",
        options={"A": "x", "B": "y"},
    )


# --- pick_mcqs ------------------------------------------------------------


def test_pick_prefers_on_lesson() -> None:
    target = uuid.uuid4()
    other = uuid.uuid4()
    on = _mcq(target)
    off_1 = _mcq(other)
    off_2 = _mcq(other)
    picked = pick_mcqs([off_1, on, off_2], lesson_id=target)  # type: ignore[arg-type]
    assert picked[0] is on, "on-lesson MCQ should come first"
    assert len(picked) == 3


def test_pick_respects_limit() -> None:
    target = uuid.uuid4()
    bank = [_mcq(target) for _ in range(10)]
    picked = pick_mcqs(bank, lesson_id=target, limit=3)  # type: ignore[arg-type]
    assert len(picked) == 3


def test_pick_empty_bank() -> None:
    assert pick_mcqs([], lesson_id=uuid.uuid4()) == []


def test_pick_mixes_on_and_off_when_thin() -> None:
    target = uuid.uuid4()
    other = uuid.uuid4()
    on = _mcq(target)
    off = _mcq(other)
    picked = pick_mcqs([off, on], lesson_id=target)  # type: ignore[arg-type]
    assert picked == [on, off]


# --- update_confidence_ema ------------------------------------------------


def test_ema_correct_raises_confidence() -> None:
    assert update_confidence_ema(0.5, correct=True) > 0.5


def test_ema_wrong_lowers_confidence() -> None:
    assert update_confidence_ema(0.5, correct=False) < 0.5


def test_ema_never_exceeds_one() -> None:
    c = 0.99
    for _ in range(50):
        c = update_confidence_ema(c, correct=True)
    assert c <= 1.0


def test_ema_never_drops_below_zero() -> None:
    c = 0.01
    for _ in range(50):
        c = update_confidence_ema(c, correct=False)
    assert c >= 0.0


def test_ema_alpha_is_twenty_percent() -> None:
    # Starting at 0.0, one correct nudges by alpha = 0.2 exactly.
    assert update_confidence_ema(0.0, correct=True) == 0.2
    # Starting at 1.0, one wrong nudges by alpha = 0.2 — so 0.8.
    assert update_confidence_ema(1.0, correct=False) == 0.8
