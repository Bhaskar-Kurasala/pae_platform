"""Pure-function tests for the Receipts gap ranker (P3 3A-16)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.services.gap_analysis_service import (
    MASTERY_CEILING,
    STALE_DAYS,
    SkillGap,
    format_last_touched,
    rank_gaps,
)


# Lightweight stand-ins so we don't need the DB to test the ranker.
@dataclass
class _State:
    skill_id: uuid.UUID
    confidence: float
    last_touched_at: datetime | None


@dataclass
class _Skill:
    id: uuid.UUID
    slug: str
    name: str


def _pair(
    slug: str, name: str, mastery: float, days_ago: int | None
) -> tuple[_State, _Skill]:
    skill_id = uuid.uuid4()
    now = datetime(2026, 4, 18, tzinfo=UTC)
    lt = None if days_ago is None else now - timedelta(days=days_ago)
    return (
        _State(skill_id=skill_id, confidence=mastery, last_touched_at=lt),
        _Skill(id=skill_id, slug=slug, name=name),
    )


_NOW = datetime(2026, 4, 18, tzinfo=UTC)


def test_rank_filters_recent_skills() -> None:
    # Touched 5 days ago — within the stale window — should not qualify
    # even with low mastery.
    pairs = [_pair("rag", "RAG", 0.2, days_ago=5)]
    gaps = rank_gaps(pairs, now=_NOW)
    assert gaps == []


def test_rank_filters_mastered_skills() -> None:
    # Stale but mastered — not a gap.
    pairs = [_pair("rag", "RAG", 0.9, days_ago=40)]
    gaps = rank_gaps(pairs, now=_NOW)
    assert gaps == []


def test_rank_keeps_stale_and_low_mastery() -> None:
    pairs = [_pair("rag", "RAG", 0.2, days_ago=30)]
    gaps = rank_gaps(pairs, now=_NOW)
    assert len(gaps) == 1
    assert gaps[0].skill_slug == "rag"
    assert gaps[0].days_since_touched == 30
    assert gaps[0].mastery == 0.2


def test_rank_orders_stalest_first_then_lowest_mastery() -> None:
    pairs = [
        _pair("a", "A", 0.4, days_ago=22),
        _pair("b", "B", 0.1, days_ago=60),
        _pair("c", "C", 0.3, days_ago=60),  # tied with b, lower mastery wins b first
    ]
    gaps = rank_gaps(pairs, now=_NOW)
    assert [g.skill_slug for g in gaps] == ["b", "c", "a"]


def test_rank_respects_limit() -> None:
    pairs = [
        _pair(str(i), str(i), 0.1, days_ago=30 + i) for i in range(10)
    ]
    gaps = rank_gaps(pairs, now=_NOW, limit=3)
    assert len(gaps) == 3


def test_untouched_skill_ranks_above_touched() -> None:
    # never-touched skill should come before a 40-day-stale one under
    # the infinite-floor convention.
    pairs = [
        _pair("recent", "R", 0.2, days_ago=40),
        _pair("never", "N", 0.2, days_ago=None),
    ]
    gaps = rank_gaps(pairs, now=_NOW)
    assert [g.skill_slug for g in gaps] == ["never", "recent"]


def test_constants_match_ticket() -> None:
    # Guard: the ticket mandates 21-day / 0.5 thresholds. Drift should
    # require a deliberate code + test change.
    assert STALE_DAYS == 21
    assert MASTERY_CEILING == 0.5


# --- format_last_touched ---------------------------------------------------


def _gap(days_ago: int | None) -> SkillGap:
    return SkillGap(
        skill_id=uuid.uuid4(),
        skill_slug="s",
        skill_name="S",
        mastery=0.2,
        last_touched_at=(
            None if days_ago is None else _NOW - timedelta(days=days_ago)
        ),
        days_since_touched=365 if days_ago is None else days_ago,
    )


def test_format_never_touched() -> None:
    assert format_last_touched(_gap(None), now=_NOW) == "never touched"


def test_format_day_granularity() -> None:
    assert format_last_touched(_gap(1), now=_NOW) == "1 day ago"
    assert format_last_touched(_gap(6), now=_NOW) == "6 days ago"


def test_format_week_granularity() -> None:
    assert format_last_touched(_gap(7), now=_NOW) == "1 week ago"
    assert format_last_touched(_gap(20), now=_NOW) == "2 weeks ago"


def test_format_month_granularity() -> None:
    assert format_last_touched(_gap(30), now=_NOW) == "1 month ago"
    assert format_last_touched(_gap(60), now=_NOW) == "2 months ago"


def test_format_caps_at_three_plus_months() -> None:
    assert format_last_touched(_gap(200), now=_NOW) == "3+ months ago"
