"""Pure tests for 3B #85 interleaving helpers."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.services.interleaving_service import (
    pick_adjacent_skill,
    should_interleave,
)


def _u() -> UUID:
    return uuid4()


def test_should_interleave_fires_on_three_in_a_row() -> None:
    a = _u()
    assert should_interleave([a, a, a]) is True


def test_should_interleave_fires_on_three_even_with_older_different() -> None:
    a, b = _u(), _u()
    # Most-recent-first: a,a,a are the first three
    assert should_interleave([a, a, a, b, b]) is True


def test_should_interleave_false_when_newest_differs() -> None:
    a, b = _u(), _u()
    assert should_interleave([a, b, a]) is False


def test_should_interleave_false_when_too_few() -> None:
    a = _u()
    assert should_interleave([a, a]) is False


def test_should_interleave_false_when_newest_is_none() -> None:
    a = _u()
    assert should_interleave([None, a, a, a]) is False


def test_should_interleave_respects_custom_threshold() -> None:
    a = _u()
    assert should_interleave([a, a], threshold=2) is True
    assert should_interleave([a, _u()], threshold=2) is False


def test_pick_adjacent_prefers_outgoing_related() -> None:
    cur, out, into = _u(), _u(), _u()
    edges = [
        (cur, out, "related"),
        (into, cur, "related"),
    ]
    assert pick_adjacent_skill(cur, edges) == out


def test_pick_adjacent_falls_back_to_incoming_related() -> None:
    cur, into = _u(), _u()
    edges = [(into, cur, "related")]
    assert pick_adjacent_skill(cur, edges) == into


def test_pick_adjacent_ignores_prereq_edges() -> None:
    cur, other = _u(), _u()
    edges = [(cur, other, "prereq")]
    assert pick_adjacent_skill(cur, edges) is None


def test_pick_adjacent_excludes_already_recent() -> None:
    cur, saturated, fresh = _u(), _u(), _u()
    edges = [
        (cur, saturated, "related"),
        (cur, fresh, "related"),
    ]
    assert pick_adjacent_skill(
        cur, edges, already_recent={saturated}
    ) == fresh


def test_pick_adjacent_excludes_self_even_if_edge_loops() -> None:
    cur = _u()
    edges = [(cur, cur, "related")]
    assert pick_adjacent_skill(cur, edges) is None


def test_pick_adjacent_returns_none_when_no_edges() -> None:
    assert pick_adjacent_skill(_u(), []) is None
