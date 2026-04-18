"""Pure tests for 3B #5 weekly-hours → daily-minutes helper."""

from __future__ import annotations

from app.services.goal_contract_service import daily_minutes_target


def test_low_bucket_returns_conservative_daily_minutes() -> None:
    assert daily_minutes_target("3-5") == 35


def test_mid_bucket_roughly_doubles() -> None:
    assert daily_minutes_target("6-10") == 70


def test_high_bucket_is_capped() -> None:
    assert daily_minutes_target("11+") == 110


def test_none_falls_back_to_low_bucket() -> None:
    assert daily_minutes_target(None) == 35


def test_unknown_bucket_falls_back_safely() -> None:
    assert daily_minutes_target("20+") == 35


def test_buckets_are_monotonically_increasing() -> None:
    lo = daily_minutes_target("3-5")
    mid = daily_minutes_target("6-10")
    hi = daily_minutes_target("11+")
    assert lo < mid < hi
