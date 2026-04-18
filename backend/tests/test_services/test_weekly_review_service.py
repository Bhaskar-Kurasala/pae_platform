"""Pure tests for 3B #93 weekly-review helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.services.weekly_review_service import (
    ReviewCard,
    assemble_quiz,
    compute_days_overdue,
    rank_due_cards,
)


_UTC = timezone.utc


def _rc(
    *,
    card_id: UUID | None = None,
    concept: str = "tokenization",
    prompt: str = "What is a token?",
    overdue: int = 0,
) -> ReviewCard:
    return ReviewCard(
        card_id=card_id or uuid4(),
        concept_key=concept,
        prompt=prompt,
        days_overdue=overdue,
    )


def test_compute_days_overdue_positive() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    due = now - timedelta(days=3)
    assert compute_days_overdue(due, now=now) == 3


def test_compute_days_overdue_zero_when_due_today() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    assert compute_days_overdue(now, now=now) == 0


def test_compute_days_overdue_zero_when_future() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    future = now + timedelta(days=5)
    assert compute_days_overdue(future, now=now) == 0


def test_compute_days_overdue_coerces_naive_to_utc() -> None:
    now_naive = datetime(2026, 4, 18, 12, 0)
    due_naive = datetime(2026, 4, 15, 12, 0)
    assert compute_days_overdue(due_naive, now=now_naive) == 3


def test_rank_most_overdue_first() -> None:
    a = _rc(overdue=1)
    b = _rc(overdue=7)
    c = _rc(overdue=3)
    ranked = rank_due_cards([a, b, c])
    assert [r.days_overdue for r in ranked] == [7, 3, 1]


def test_rank_caps_at_limit() -> None:
    cards = [_rc(overdue=i) for i in range(20)]
    ranked = rank_due_cards(cards, limit=5)
    assert len(ranked) == 5
    assert ranked[0].days_overdue == 19


def test_rank_ties_break_by_card_id_for_stability() -> None:
    same_overdue = [_rc(overdue=3) for _ in range(5)]
    ranked = rank_due_cards(same_overdue)
    ids = [str(c.card_id) for c in ranked]
    assert ids == sorted(ids)


def test_assemble_wraps_ranked_cards() -> None:
    uid = uuid4()
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    quiz = assemble_quiz(
        uid,
        [_rc(overdue=1), _rc(overdue=5)],
        now=now,
    )
    assert quiz.user_id == uid
    assert quiz.generated_at == now
    assert quiz.cards[0].days_overdue == 5


def test_assemble_is_empty_when_no_due() -> None:
    uid = uuid4()
    now = datetime(2026, 4, 18, tzinfo=_UTC)
    quiz = assemble_quiz(uid, [], now=now)
    assert quiz.cards == ()


def test_assemble_respects_limit() -> None:
    uid = uuid4()
    now = datetime(2026, 4, 18, tzinfo=_UTC)
    cards = [_rc(overdue=i) for i in range(15)]
    quiz = assemble_quiz(uid, cards, now=now, limit=3)
    assert len(quiz.cards) == 3
