"""F1 — student_risk_service unit tests.

The classify function is intentionally pure — given a _UserState
snapshot, it returns a RiskSignal. We test it WITHOUT a DB by
constructing _UserState fixtures directly. The integration with
score_all_users (DB upsert + Celery wrapper) gets a single
end-to-end test using the regular conftest session.

Coverage matrix: each of the 6 slip patterns gets its own test
fixture verifying the pattern, the priority order, and the score
ordering. Plus 3 negative cases (none state, stale-but-paid,
healthy-streak) and 1 priority-conflict test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.student_risk_service import (
    SCORE_BASE,
    _UserState,
    classify,
)


def _user(*, id: uuid.UUID | None = None, created_days_ago: int = 30):
    """Build a minimal User-shaped object the classify function reads.

    SimpleNamespace beats mocking SQLAlchemy declarative — classify
    only touches `.id` and `.created_at` on User.
    """
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        created_at=datetime.now(UTC) - timedelta(days=created_days_ago),
    )


def _state(
    *,
    user=None,
    last_session_days_ago: int | None = None,
    sessions_count: int = 0,
    max_streak: int = 0,
    paid_days_ago: int | None = None,
    capstone_started_days_ago: int | None = None,
    last_capstone_draft_days_ago: int | None = None,
    last_review_passed_days_ago: int | None = None,
    last_promotion_attempt_days_ago: int | None = None,
) -> _UserState:
    """Fixture builder. None means 'never happened'."""
    now = datetime.now(UTC)

    def _ago(d):
        return now - timedelta(days=d) if d is not None else None

    return _UserState(
        user=user or _user(),
        last_session_at=_ago(last_session_days_ago),
        sessions_count=sessions_count,
        max_streak=max_streak,
        paid_at=_ago(paid_days_ago),
        capstone_started_at=_ago(capstone_started_days_ago),
        last_capstone_draft_at=_ago(last_capstone_draft_days_ago),
        last_review_passed_at=_ago(last_review_passed_days_ago),
        last_promotion_attempt_at=_ago(last_promotion_attempt_days_ago),
    )


# ---------------------------------------------------------------------------
# Per-pattern positive cases
# ---------------------------------------------------------------------------


def test_cold_signup_pattern() -> None:
    """Brand-new user, no sessions, day 2+."""
    state = _state(
        user=_user(created_days_ago=3),
        last_session_days_ago=None,
        sessions_count=0,
    )
    sig = classify(state)
    assert sig.slip_type == "cold_signup"
    assert sig.recommended_intervention == "cold_signup_day_1"
    assert "Registered 3d ago" in (sig.risk_reason or "")
    # cold_signup is lowest priority — score should be lowest of the slip types
    assert sig.risk_score == SCORE_BASE["cold_signup"]


def test_unpaid_stalled_pattern() -> None:
    """Did first session, no payment, >7 days silent."""
    state = _state(
        sessions_count=3,
        last_session_days_ago=10,
    )
    sig = classify(state)
    assert sig.slip_type == "unpaid_stalled"
    assert sig.recommended_intervention == "unpaid_stalled_day_7"
    # Linear staleness bonus: 10 days // 2 = 5 added on top of base
    assert sig.risk_score == SCORE_BASE["unpaid_stalled"] + 5


def test_streak_broken_pattern() -> None:
    """Had a 5-day streak, now silent 6 days."""
    state = _state(
        sessions_count=10,
        max_streak=5,
        last_session_days_ago=6,
    )
    sig = classify(state)
    assert sig.slip_type == "streak_broken"
    assert sig.recommended_intervention == "streak_broken_day_5"
    assert "5-day streak" in (sig.risk_reason or "")


def test_paid_silent_pattern() -> None:
    """Worst case — paid recently, gone silent."""
    state = _state(
        sessions_count=4,
        last_session_days_ago=10,
        paid_days_ago=15,
    )
    sig = classify(state)
    assert sig.slip_type == "paid_silent"
    assert sig.recommended_intervention == "paid_silent_day_3"
    assert sig.paid is True
    # paid_silent is highest priority — score should reflect it
    assert sig.risk_score >= 80


def test_capstone_stalled_pattern() -> None:
    """Capstone started, no draft activity in 14+ days."""
    state = _state(
        sessions_count=20,
        last_session_days_ago=2,  # still using app
        capstone_started_days_ago=30,
        last_capstone_draft_days_ago=20,
    )
    sig = classify(state)
    assert sig.slip_type == "capstone_stalled"
    assert sig.recommended_intervention == "capstone_stalled_day_7"
    assert "20d ago" in (sig.risk_reason or "")


def test_promotion_avoidant_pattern() -> None:
    """Passed senior review, never claimed promotion gate."""
    state = _state(
        sessions_count=15,
        last_session_days_ago=2,
        last_review_passed_days_ago=10,
        last_promotion_attempt_days_ago=None,
    )
    sig = classify(state)
    assert sig.slip_type == "promotion_avoidant"
    assert sig.recommended_intervention == "promotion_avoidant_day_3"


# ---------------------------------------------------------------------------
# Negative / healthy cases
# ---------------------------------------------------------------------------


def test_healthy_user_returns_none() -> None:
    """Active user, no slip pattern detected."""
    state = _state(
        sessions_count=5,
        max_streak=2,
        last_session_days_ago=1,
    )
    sig = classify(state)
    assert sig.slip_type == "none"
    assert sig.recommended_intervention is None
    assert sig.risk_score == 0


def test_brand_new_user_within_24h_is_none() -> None:
    """User signed up today — too early to flag as cold_signup."""
    state = _state(
        user=_user(created_days_ago=0),
        sessions_count=0,
    )
    sig = classify(state)
    assert sig.slip_type == "none"


def test_streak_under_threshold_doesnt_count() -> None:
    """User had a 2-day streak (below STREAK_RECOVERED_MIN_LENGTH=3),
    silent — should NOT flag streak_broken."""
    state = _state(
        sessions_count=2,
        max_streak=2,  # below threshold
        last_session_days_ago=10,
    )
    sig = classify(state)
    # Falls through to unpaid_stalled (sessions >=1, no payment, >7d silent)
    assert sig.slip_type == "unpaid_stalled"


# ---------------------------------------------------------------------------
# Priority order tests (when multiple patterns match)
# ---------------------------------------------------------------------------


def test_paid_silent_beats_streak_broken() -> None:
    """User had a streak AND paid AND went silent — paid_silent wins."""
    state = _state(
        sessions_count=10,
        max_streak=5,
        last_session_days_ago=10,
        paid_days_ago=15,
    )
    sig = classify(state)
    # Both patterns match; paid_silent wins.
    assert sig.slip_type == "paid_silent"


def test_capstone_stalled_beats_streak_broken() -> None:
    """Capstone-stalled has higher priority than streak-broken."""
    state = _state(
        sessions_count=10,
        max_streak=5,
        last_session_days_ago=2,
        capstone_started_days_ago=30,
        last_capstone_draft_days_ago=20,
    )
    sig = classify(state)
    assert sig.slip_type == "capstone_stalled"


def test_score_ordering_matches_priority() -> None:
    """Verify the score ordering preserves priority — F4 console
    sorts by risk_score DESC, so the ordering must be:
    paid_silent > capstone_stalled > streak_broken >
    promotion_avoidant > unpaid_stalled > cold_signup > none."""
    assert (
        SCORE_BASE["paid_silent"]
        > SCORE_BASE["capstone_stalled"]
        > SCORE_BASE["streak_broken"]
        > SCORE_BASE["promotion_avoidant"]
        > SCORE_BASE["unpaid_stalled"]
        > SCORE_BASE["cold_signup"]
        > SCORE_BASE["none"]
    )


def test_score_clamps_at_100() -> None:
    """Even with maximum staleness bonus, score never exceeds 100."""
    state = _state(
        sessions_count=4,
        last_session_days_ago=365,  # extreme staleness
        paid_days_ago=15,
    )
    sig = classify(state)
    assert sig.risk_score <= 100


# ---------------------------------------------------------------------------
# Naive datetime safety (SQLite test fixtures)
# ---------------------------------------------------------------------------


def test_naive_datetime_doesnt_blow_up() -> None:
    """SQLite test conftest sometimes returns naive datetimes (no
    tzinfo). The classify code path normalizes both sides to UTC-aware
    so the subtraction doesn't TypeError."""
    naive_user = SimpleNamespace(
        id=uuid.uuid4(),
        created_at=datetime.now() - timedelta(days=3),  # naive
    )
    state = _UserState(
        user=naive_user,
        last_session_at=None,
        sessions_count=0,
        max_streak=0,
        paid_at=None,
        capstone_started_at=None,
        last_capstone_draft_at=None,
        last_review_passed_at=None,
        last_promotion_attempt_at=None,
    )
    # Should classify cleanly without raising.
    sig = classify(state)
    assert sig.slip_type == "cold_signup"
