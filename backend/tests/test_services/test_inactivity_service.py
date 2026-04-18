"""Pure tests for 3B #152 inactivity helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.inactivity_service import (
    days_since,
    filter_inactive,
    is_inactive,
)

_UTC = timezone.utc


def test_is_inactive_true_past_threshold() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    last = now - timedelta(days=8)
    assert is_inactive(last, now=now) is True


def test_is_inactive_false_within_threshold() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    last = now - timedelta(days=3)
    assert is_inactive(last, now=now) is False


def test_is_inactive_true_when_never_active() -> None:
    now = datetime(2026, 4, 18, tzinfo=_UTC)
    assert is_inactive(None, now=now) is True


def test_is_inactive_respects_custom_threshold() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    last = now - timedelta(days=3)
    assert is_inactive(last, now=now, threshold_days=2) is True
    assert is_inactive(last, now=now, threshold_days=5) is False


def test_is_inactive_coerces_naive_to_utc() -> None:
    now = datetime(2026, 4, 18, 12, 0)
    last = datetime(2026, 4, 1, 12, 0)
    assert is_inactive(last, now=now) is True


def test_days_since_none_returns_large_sentinel() -> None:
    now = datetime(2026, 4, 18, tzinfo=_UTC)
    assert days_since(None, now=now) >= 999


def test_days_since_computes_whole_days() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    last = now - timedelta(days=9, hours=2)
    assert days_since(last, now=now) == 9


def test_filter_inactive_drops_active_and_keeps_dormant() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    active_uid = uuid4()
    dormant_uid = uuid4()
    never_uid = uuid4()
    rows = [
        (active_uid, now - timedelta(days=1)),
        (dormant_uid, now - timedelta(days=10)),
        (never_uid, None),
    ]
    result = filter_inactive(rows, now=now)
    uids = {r.user_id for r in result}
    assert active_uid not in uids
    assert dormant_uid in uids
    assert never_uid in uids


def test_filter_inactive_populates_days_inactive() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=_UTC)
    uid = uuid4()
    rows = [(uid, now - timedelta(days=14))]
    result = filter_inactive(rows, now=now)
    assert result[0].days_inactive == 14
