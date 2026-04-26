"""Pure tests for goal_contract days_remaining helper.

Covers the new `days_remaining()` helper added in the Today refactor:
- floors at 0 when expired
- handles naive datetimes by treating them as UTC
- computes against `created_at + deadline_months * 30 days`
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.goal_contract_service import days_remaining


def _contract(
    *, created_at: datetime, deadline_months: int = 6
) -> SimpleNamespace:
    """Lightweight stand-in for a GoalContract row — only the fields the
    helper inspects.
    """
    return SimpleNamespace(
        created_at=created_at, deadline_months=deadline_months
    )


def test_days_remaining_full_window_when_just_created() -> None:
    created = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    contract = _contract(created_at=created, deadline_months=6)
    assert days_remaining(contract, now=created) == 6 * 30


def test_days_remaining_subtracts_elapsed_days() -> None:
    created = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    contract = _contract(created_at=created, deadline_months=3)
    now = created + timedelta(days=30)
    # 90 - 30 = 60
    assert days_remaining(contract, now=now) == 60


def test_days_remaining_floors_at_zero_when_expired() -> None:
    created = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    contract = _contract(created_at=created, deadline_months=1)
    # 30 days deadline; we're 365 days out
    far_future = created + timedelta(days=365)
    assert days_remaining(contract, now=far_future) == 0


def test_days_remaining_handles_naive_now_as_utc() -> None:
    created = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    contract = _contract(created_at=created, deadline_months=2)
    naive_now = datetime(2026, 4, 11, 0, 0)  # 10 days later, naive
    assert days_remaining(contract, now=naive_now) == 60 - 10


def test_days_remaining_handles_naive_created_at_as_utc() -> None:
    naive_created = datetime(2026, 4, 1, 0, 0)  # naive
    contract = _contract(created_at=naive_created, deadline_months=1)
    now = datetime(2026, 4, 11, 0, 0, tzinfo=UTC)
    # 30 - 10 = 20
    assert days_remaining(contract, now=now) == 20


def test_days_remaining_defaults_now_to_current_utc() -> None:
    """When `now` is omitted the helper still returns a non-negative int."""
    created = datetime.now(UTC) - timedelta(days=5)
    contract = _contract(created_at=created, deadline_months=12)
    out = days_remaining(contract)
    # 12*30 - 5 = 355, allow ±2 for clock drift inside the call
    assert 353 <= out <= 357


def test_days_remaining_exactly_at_deadline_returns_zero() -> None:
    created = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    contract = _contract(created_at=created, deadline_months=1)
    at_deadline = created + timedelta(days=30)
    assert days_remaining(contract, now=at_deadline) == 0
