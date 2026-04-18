"""Pure tests for 3B #91 worked-example helpers."""

from __future__ import annotations

from uuid import uuid4

from app.services.worked_example_service import (
    WorkedExampleCandidate,
    rank_candidates,
    to_worked_example,
    trim_code,
)


def _c(
    *,
    exercise_id=None,
    score: int = 80,
    is_own: bool = False,
    title: str = "Some Exercise",
    code: str = "print('hi')",
    note: str | None = None,
) -> WorkedExampleCandidate:
    return WorkedExampleCandidate(
        submission_id=uuid4(),
        exercise_id=exercise_id or uuid4(),
        exercise_title=title,
        score=score,
        code=code,
        share_note=note,
        is_own=is_own,
    )


def test_rank_filters_out_current_exercise() -> None:
    current = uuid4()
    a = _c(exercise_id=current)
    b = _c()
    ranked = rank_candidates([a, b], current_exercise_id=current)
    assert len(ranked) == 1
    assert ranked[0].exercise_id != current


def test_rank_prefers_own_solutions() -> None:
    peer = _c(score=95, is_own=False, title="peer")
    own = _c(score=75, is_own=True, title="own")
    ranked = rank_candidates([peer, own], current_exercise_id=uuid4())
    assert ranked[0].exercise_title == "own"


def test_rank_within_own_sorts_by_score_desc() -> None:
    lo = _c(score=72, is_own=True, title="lo")
    hi = _c(score=90, is_own=True, title="hi")
    ranked = rank_candidates([lo, hi], current_exercise_id=uuid4())
    assert [c.exercise_title for c in ranked] == ["hi", "lo"]


def test_rank_within_peers_sorts_by_score_desc() -> None:
    lo = _c(score=72, is_own=False, title="lo")
    hi = _c(score=90, is_own=False, title="hi")
    ranked = rank_candidates([lo, hi], current_exercise_id=uuid4())
    assert [c.exercise_title for c in ranked] == ["hi", "lo"]


def test_trim_code_keeps_short_as_is() -> None:
    assert trim_code("print(1)") == "print(1)"


def test_trim_code_truncates_long() -> None:
    src = "x" * 3000
    out = trim_code(src, limit=500)
    assert len(out) <= 600  # 500 + truncation marker
    assert out.startswith("x" * 500)
    assert "truncated" in out


def test_to_worked_example_own_label() -> None:
    out = to_worked_example(_c(is_own=True))
    assert out.source == "your earlier solution"


def test_to_worked_example_peer_label() -> None:
    out = to_worked_example(_c(is_own=False))
    assert out.source == "peer solution"


def test_to_worked_example_passes_through_fields() -> None:
    c = _c(title="Tokens 101", code="x=1", note="watch the types", is_own=True)
    out = to_worked_example(c)
    assert out.exercise_title == "Tokens 101"
    assert out.code_snippet == "x=1"
    assert out.note == "watch the types"


def test_rank_returns_empty_when_all_are_current() -> None:
    cur = uuid4()
    assert rank_candidates(
        [_c(exercise_id=cur), _c(exercise_id=cur)], current_exercise_id=cur
    ) == []
