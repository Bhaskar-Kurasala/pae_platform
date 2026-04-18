"""Unit tests for conversation_memory_service pure helpers (P3 3A-2).

Covers trimming, age bucketing, and line rendering. DB-level upsert + load
is covered by `test_conversation_memory_cross_session.py` which uses the
in-memory SQLite fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.conversation_memory_service import (
    MemoryEntry,
    _age_hours,
    _format_age,
    _trim_summary,
    render_memory_lines,
)


# ── _trim_summary ─────────────────────────────────────────────────────────────


def test_trim_short_summary_unchanged() -> None:
    assert _trim_summary("short text") == "short text"


def test_trim_strips_whitespace() -> None:
    assert _trim_summary("  hello  ") == "hello"


def test_trim_handles_none_like() -> None:
    assert _trim_summary("") == ""


def test_trim_long_summary_on_word_boundary() -> None:
    # 300-char summary should truncate to <= 180 on a word boundary.
    text = ("lorem ipsum " * 30).strip()
    trimmed = _trim_summary(text, limit=180)
    assert len(trimmed) <= 180
    assert trimmed.endswith("…")
    # Must not end mid-word (the ellipsis sits right after a real word).
    assert " " in trimmed  # boundary preserved


def test_trim_long_without_spaces_still_caps() -> None:
    text = "x" * 500
    trimmed = _trim_summary(text, limit=50)
    assert len(trimmed) <= 50
    assert trimmed.endswith("…")


# ── _age_hours ────────────────────────────────────────────────────────────────


def test_age_hours_none() -> None:
    assert _age_hours(None, datetime.now(UTC)) == 0


def test_age_hours_basic() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    past = now - timedelta(hours=5)
    assert _age_hours(past, now) == 5


def test_age_hours_naive_treated_as_utc() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 4, 18, 9, 0)
    assert _age_hours(naive, now) == 3


def test_age_hours_future_clamped_to_zero() -> None:
    now = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    future = now + timedelta(hours=2)
    assert _age_hours(future, now) == 0


# ── _format_age ───────────────────────────────────────────────────────────────


def test_format_age_just_now() -> None:
    assert _format_age(0) == "just now"


def test_format_age_hours() -> None:
    assert _format_age(3) == "3h ago"


def test_format_age_days() -> None:
    assert _format_age(49) == "2d ago"


# ── render_memory_lines ───────────────────────────────────────────────────────


def _entry(
    slug: str = "vectors",
    name: str = "Vector embeddings",
    summary: str = "worked through dot product vs cosine",
    age: int = 5,
) -> MemoryEntry:
    return MemoryEntry(
        skill_slug=slug,
        skill_name=name,
        summary_text=summary,
        age_hours=age,
    )


def test_render_empty_returns_empty_list() -> None:
    assert render_memory_lines([]) == []


def test_render_single_memory() -> None:
    lines = render_memory_lines([_entry()])
    assert len(lines) == 1
    assert "Vector embeddings" in lines[0]
    assert "dot product" in lines[0]
    assert "5h ago" in lines[0]


def test_render_multiple_preserves_order() -> None:
    lines = render_memory_lines([
        _entry(name="Prompting", summary="few-shot vs chain-of-thought", age=2),
        _entry(name="RAG", summary="chunking strategies", age=30),
    ])
    assert len(lines) == 2
    assert "Prompting" in lines[0]
    assert "RAG" in lines[1]
    assert "2h ago" in lines[0]
    assert "1d ago" in lines[1]
