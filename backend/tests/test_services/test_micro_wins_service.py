"""Pure tests for 3A-17 micro-wins helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.micro_wins_service import (
    MicroWin,
    format_hard_exercise_label,
    format_lesson_label,
    format_misconception_label,
    rank_wins,
    window_start,
)


def test_window_start_is_48h_back() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    assert window_start(now) == now - timedelta(hours=48)


def test_window_start_accepts_naive() -> None:
    now = datetime(2026, 4, 18, 12, 0)
    assert window_start(now).tzinfo is UTC


def test_rank_wins_is_newest_first() -> None:
    older = MicroWin(
        kind="lesson_completed",
        label="A",
        occurred_at=datetime(2026, 4, 17, 9, 0, tzinfo=UTC),
    )
    newer = MicroWin(
        kind="lesson_completed",
        label="B",
        occurred_at=datetime(2026, 4, 18, 9, 0, tzinfo=UTC),
    )
    out = rank_wins([older, newer])
    assert [w.label for w in out] == ["B", "A"]


def test_rank_wins_caps_at_limit() -> None:
    wins = [
        MicroWin(
            kind="lesson_completed",
            label=f"L{i}",
            occurred_at=datetime(2026, 4, 18, i, 0, tzinfo=UTC),
        )
        for i in range(10)
    ]
    out = rank_wins(wins, limit=3)
    assert len(out) == 3
    assert [w.label for w in out] == ["L9", "L8", "L7"]


def test_rank_wins_ties_break_by_kind_for_stability() -> None:
    ts = datetime(2026, 4, 18, 10, 0, tzinfo=UTC)
    a = MicroWin(kind="hard_exercise_passed", label="x", occurred_at=ts)
    b = MicroWin(kind="lesson_completed", label="y", occurred_at=ts)
    c = MicroWin(kind="misconception_resolved", label="z", occurred_at=ts)
    out = rank_wins([a, b, c])
    # reverse sort on kind: misconception_resolved > lesson_completed > hard_...
    assert [w.kind for w in out] == [
        "misconception_resolved",
        "lesson_completed",
        "hard_exercise_passed",
    ]


def test_misconception_label_uses_topic() -> None:
    assert "async" in format_misconception_label("async/await ordering")


def test_misconception_label_has_fallback() -> None:
    assert format_misconception_label("") == "You worked through a mistaken assumption"
    assert format_misconception_label("   ") == "You worked through a mistaken assumption"


def test_lesson_label_quotes_title() -> None:
    out = format_lesson_label("Intro to Prompts")
    assert "Intro to Prompts" in out
    assert "finished" in out


def test_lesson_label_has_fallback() -> None:
    assert format_lesson_label("") == "You completed a lesson"


def test_hard_exercise_label_mentions_hard() -> None:
    out = format_hard_exercise_label("Token Accounting")
    assert "hard" in out.lower()
    assert "Token Accounting" in out


def test_hard_exercise_label_has_fallback() -> None:
    assert format_hard_exercise_label("") == "You passed a hard exercise"
