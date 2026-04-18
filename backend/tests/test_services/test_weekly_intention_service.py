"""Pure tests for 3B #151 weekly-intention helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.weekly_intention_service import (
    current_week_starting,
    normalize_focus_items,
    week_starting,
)


def test_week_starting_monday_is_itself() -> None:
    assert week_starting(date(2026, 4, 13)) == date(2026, 4, 13)  # Mon


def test_week_starting_sunday_goes_back_to_monday() -> None:
    assert week_starting(date(2026, 4, 19)) == date(2026, 4, 13)  # Sun → Mon


def test_week_starting_wednesday_snaps_back() -> None:
    assert week_starting(date(2026, 4, 15)) == date(2026, 4, 13)


def test_current_week_starting_uses_now() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)  # Sat
    assert current_week_starting(now) == date(2026, 4, 13)


def test_normalize_strips_and_drops_empties() -> None:
    out = normalize_focus_items(["  learn RAG  ", "", "   "])
    assert out == ["learn RAG"]


def test_normalize_dedups_case_insensitively() -> None:
    out = normalize_focus_items(["Learn RAG", "learn rag", "Ship Demo"])
    assert out == ["Learn RAG", "Ship Demo"]


def test_normalize_caps_at_three() -> None:
    out = normalize_focus_items(["a", "b", "c", "d", "e"])
    assert out == ["a", "b", "c"]


def test_normalize_truncates_long_text() -> None:
    long = "x" * 400
    out = normalize_focus_items([long])
    assert len(out[0]) == 280


def test_normalize_empty_list_returns_empty() -> None:
    assert normalize_focus_items([]) == []
