"""Pure tests for daily-intention helpers (P3 3A-11)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone

from app.services.daily_intention_service import normalize_text, today_in_utc


def test_normalize_strips_whitespace() -> None:
    assert normalize_text("  ship the quiz  ") == "ship the quiz"


def test_normalize_preserves_interior() -> None:
    assert normalize_text("a\tb c") == "a\tb c"


def test_today_in_utc_accepts_aware_datetime() -> None:
    dt = datetime(2026, 4, 18, 23, 30, tzinfo=UTC)
    assert today_in_utc(dt) == date(2026, 4, 18)


def test_today_in_utc_converts_offset() -> None:
    # 23:30 Pacific (-08:00) is 07:30 UTC the next morning.
    pacific = timezone.offset_delta = None  # noqa: F841 - placeholder; see below
    from datetime import timedelta

    pst = timezone(timedelta(hours=-8))
    dt_pst = datetime(2026, 4, 17, 23, 30, tzinfo=pst)
    assert today_in_utc(dt_pst) == date(2026, 4, 18)


def test_today_in_utc_naive_gets_utc() -> None:
    # Naive datetime is treated as UTC rather than rejected — our DB
    # column is date-typed anyway, so the worst case is a 24-hour drift
    # which a later real-timestamp write will correct.
    naive = datetime(2026, 4, 18, 12, 0)
    assert today_in_utc(naive) == date(2026, 4, 18)
