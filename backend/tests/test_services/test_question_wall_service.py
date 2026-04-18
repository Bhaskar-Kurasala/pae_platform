"""Pure tests for 3B #102 question-wall helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.question_wall_service import (
    filter_visible,
    normalize_body,
    normalize_vote_kind,
    rank_posts,
    should_hide,
)


@dataclass
class _FakePost:
    upvote_count: int = 0
    flag_count: int = 0
    is_deleted: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime(2026, 4, 18, tzinfo=timezone.utc)
    )


def test_normalize_body_strips_and_caps() -> None:
    assert normalize_body("  hello  ") == "hello"


def test_normalize_body_truncates_long() -> None:
    long = "x" * 5000
    out = normalize_body(long)
    assert len(out) == 4000


def test_normalize_body_rejects_empty() -> None:
    try:
        normalize_body("   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_normalize_vote_kind_lowercases() -> None:
    assert normalize_vote_kind(" UPVOTE ") == "upvote"
    assert normalize_vote_kind("Flag") == "flag"


def test_normalize_vote_kind_rejects_bad() -> None:
    try:
        normalize_vote_kind("boost")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_should_hide_threshold() -> None:
    assert should_hide(2) is False
    assert should_hide(3) is True
    assert should_hide(10) is True


def test_should_hide_custom_threshold() -> None:
    assert should_hide(4, threshold=5) is False
    assert should_hide(5, threshold=5) is True


def test_rank_posts_upvotes_desc_then_earliest() -> None:
    early = datetime(2026, 4, 17, tzinfo=timezone.utc)
    late = datetime(2026, 4, 18, tzinfo=timezone.utc)
    a = _FakePost(upvote_count=5, created_at=early)
    b = _FakePost(upvote_count=5, created_at=late)
    c = _FakePost(upvote_count=10, created_at=late)
    assert rank_posts([a, b, c]) == [c, a, b]


def test_filter_visible_drops_deleted() -> None:
    a = _FakePost()
    b = _FakePost(is_deleted=True)
    assert filter_visible([a, b]) == [a]


def test_filter_visible_drops_flagged() -> None:
    a = _FakePost()
    b = _FakePost(flag_count=5)
    assert filter_visible([a, b]) == [a]


def test_filter_visible_keeps_clean_posts() -> None:
    a = _FakePost(upvote_count=3)
    b = _FakePost(flag_count=2)  # below threshold
    assert filter_visible([a, b]) == [a, b]
