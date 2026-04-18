"""Pure tests for 3B #101 peer-review helpers."""

from __future__ import annotations

import random
import uuid

from app.services.peer_review_service import (
    pick_reviewers,
    validate_review,
)


def _uuids(n: int) -> list[uuid.UUID]:
    rng = random.Random(1)
    return [
        uuid.UUID(int=rng.getrandbits(128), version=4) for _ in range(n)
    ]


def test_pick_reviewers_excludes_author() -> None:
    ids = _uuids(4)
    author = ids[0]
    pool = ids  # includes author
    picked = pick_reviewers(pool, author_id=author, rng=random.Random(0))
    assert author not in picked
    assert len(picked) == 2


def test_pick_reviewers_respects_existing() -> None:
    ids = _uuids(5)
    author = ids[0]
    existing = [ids[1]]  # one already assigned
    picked = pick_reviewers(
        ids, author_id=author, existing_reviewers=existing, rng=random.Random(0)
    )
    # Need 2 total minus 1 existing = 1 more.
    assert len(picked) == 1
    assert ids[1] not in picked
    assert author not in picked


def test_pick_reviewers_returns_empty_when_full() -> None:
    ids = _uuids(4)
    author = ids[0]
    existing = [ids[1], ids[2]]  # already 2, cap reached
    assert pick_reviewers(
        ids, author_id=author, existing_reviewers=existing
    ) == []


def test_pick_reviewers_small_pool() -> None:
    ids = _uuids(2)
    author = ids[0]
    picked = pick_reviewers(ids, author_id=author, rng=random.Random(0))
    assert picked == [ids[1]]


def test_pick_reviewers_empty_candidates() -> None:
    assert pick_reviewers([], author_id=_uuids(1)[0]) == []


def test_pick_reviewers_custom_max() -> None:
    ids = _uuids(6)
    author = ids[0]
    picked = pick_reviewers(
        ids, author_id=author, max_reviewers=3, rng=random.Random(0)
    )
    assert len(picked) == 3
    assert author not in picked


def test_validate_review_ok_rating_midrange() -> None:
    rating, comment = validate_review(3, "  nice work  ")
    assert rating == 3
    assert comment == "nice work"


def test_validate_review_trims_blank_comment_to_none() -> None:
    rating, comment = validate_review(5, "    ")
    assert rating == 5
    assert comment is None


def test_validate_review_truncates_long_comment() -> None:
    long = "x" * 5000
    _, comment = validate_review(4, long)
    assert comment is not None
    assert len(comment) == 2000


def test_validate_review_none_comment_stays_none() -> None:
    rating, comment = validate_review(1, None)
    assert rating == 1
    assert comment is None


def test_validate_review_rejects_low_rating() -> None:
    try:
        validate_review(0, "x")
    except ValueError as exc:
        assert "rating must be" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_validate_review_rejects_high_rating() -> None:
    try:
        validate_review(6, "x")
    except ValueError as exc:
        assert "rating must be" in str(exc)
        return
    raise AssertionError("expected ValueError")
