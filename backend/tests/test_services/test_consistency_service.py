"""Pure tests for consistency surfacing (P3 3A-14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.consistency_service import count_active_days, window_bounds


def test_window_bounds_spans_seven_days() -> None:
    now = datetime(2026, 4, 18, 15, 30, tzinfo=UTC)
    start, end = window_bounds(now)
    assert end == now
    assert start.date() == (now.date() - timedelta(days=6))
    assert start.hour == 0 and start.minute == 0


def test_window_bounds_accepts_naive_datetime() -> None:
    now = datetime(2026, 4, 18, 12, 0)
    start, end = window_bounds(now)
    assert start.tzinfo is UTC
    assert end.tzinfo is UTC


def test_count_active_days_dedupes_same_day() -> None:
    now = datetime(2026, 4, 18, 23, 0, tzinfo=UTC)
    start, end = window_bounds(now)
    same_day = [
        datetime(2026, 4, 18, 9, 0, tzinfo=UTC),
        datetime(2026, 4, 18, 10, 0, tzinfo=UTC),
        datetime(2026, 4, 18, 22, 0, tzinfo=UTC),
    ]
    assert count_active_days(same_day, window_start=start, window_end=end) == 1


def test_count_active_days_counts_distinct_days() -> None:
    now = datetime(2026, 4, 18, 23, 0, tzinfo=UTC)
    start, end = window_bounds(now)
    stamps = [
        datetime(2026, 4, 14, 8, 0, tzinfo=UTC),
        datetime(2026, 4, 15, 8, 0, tzinfo=UTC),
        datetime(2026, 4, 18, 8, 0, tzinfo=UTC),
    ]
    assert count_active_days(stamps, window_start=start, window_end=end) == 3


def test_count_active_days_excludes_out_of_window() -> None:
    now = datetime(2026, 4, 18, 23, 0, tzinfo=UTC)
    start, end = window_bounds(now)
    # 2026-04-10 is outside the 7-day window (2026-04-12 .. 2026-04-18)
    stamps = [
        datetime(2026, 4, 10, 8, 0, tzinfo=UTC),
        datetime(2026, 4, 18, 8, 0, tzinfo=UTC),
    ]
    assert count_active_days(stamps, window_start=start, window_end=end) == 1


def test_count_active_days_empty_window_returns_zero() -> None:
    now = datetime(2026, 4, 18, 23, 0, tzinfo=UTC)
    start, end = window_bounds(now)
    assert count_active_days([], window_start=start, window_end=end) == 0


def test_count_active_days_handles_naive_timestamps() -> None:
    now = datetime(2026, 4, 18, 23, 0, tzinfo=UTC)
    start, end = window_bounds(now)
    stamps = [datetime(2026, 4, 18, 9, 0)]  # naive → treated as UTC
    assert count_active_days(stamps, window_start=start, window_end=end) == 1
