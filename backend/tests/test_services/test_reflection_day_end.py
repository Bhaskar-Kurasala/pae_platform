"""Pure tests for day-end reflection gating (P3 3A-12)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.reflection_service import is_day_end_window


def test_before_six_pm_utc_is_closed() -> None:
    noon = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    assert is_day_end_window(noon, tz_offset_hours=0) is False


def test_exactly_six_pm_utc_opens() -> None:
    six = datetime(2026, 4, 18, 18, 0, tzinfo=UTC)
    assert is_day_end_window(six, tz_offset_hours=0) is True


def test_pacific_offset_opens_earlier_in_utc() -> None:
    # 6pm Pacific (-08:00) is 02:00 UTC the next day — so a
    # Pacific user asking at their 6pm sees an open window even
    # though UTC clock says 02:00.
    utc_2am = datetime(2026, 4, 19, 2, 0, tzinfo=UTC)
    assert is_day_end_window(utc_2am, tz_offset_hours=-8) is True


def test_tokyo_offset_is_still_morning_at_utc_noon() -> None:
    # 12:00 UTC is 21:00 Tokyo (+09:00) — past the gate.
    noon = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    assert is_day_end_window(noon, tz_offset_hours=9) is True


def test_naive_treated_as_utc() -> None:
    naive = datetime(2026, 4, 18, 19, 0)
    assert is_day_end_window(naive, tz_offset_hours=0) is True


def test_late_morning_still_closed() -> None:
    eleven = datetime(2026, 4, 18, 11, 0, tzinfo=UTC)
    assert is_day_end_window(eleven, tz_offset_hours=0) is False
