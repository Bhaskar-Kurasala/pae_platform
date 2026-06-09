"""Tests for app/services/notebook_service (Notebook + Tutor refactor 2026-04-26).

Covers:
  - Pure helpers: concept_key_for, is_notebook_concept,
    entry_id_from_concept, all_tags
  - DB helpers: list_for_user (filter by source / graduated / tag),
    summary_for_user, maybe_graduate_card (skip non-notebook keys, skip
    below threshold, idempotent, stamps graduated_at)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notebook_entry import NotebookEntry
from app.models.srs_card import SRSCard
from app.models.user import User
from app.services.notebook_service import (
    GRADUATION_THRESHOLD_REPS,
    NOTEBOOK_CONCEPT_PREFIX,
    NotebookSummary,
    all_tags,
    concept_key_for,
    entry_id_from_concept,
    is_notebook_concept,
    list_for_user,
    maybe_graduate_card,
    summary_for_user,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_concept_key_for_uses_notebook_prefix() -> None:
    entry = NotebookEntry(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        user_id=uuid.uuid4(),
        message_id="m",
        conversation_id="c",
        content="x",
        tags=[],
    )
    key = concept_key_for(entry)
    assert key == f"{NOTEBOOK_CONCEPT_PREFIX}{entry.id}"
    assert key.startswith("notebook:")


def test_is_notebook_concept_true_for_notebook_prefix() -> None:
    assert is_notebook_concept("notebook:abc") is True
    assert is_notebook_concept("notebook:") is True


def test_is_notebook_concept_false_for_other_prefixes() -> None:
    assert is_notebook_concept("lesson:rag") is False
    assert is_notebook_concept("skill:async") is False
    assert is_notebook_concept("") is False


def test_entry_id_from_concept_parses_uuid() -> None:
    eid = uuid.uuid4()
    parsed = entry_id_from_concept(f"notebook:{eid}")
    assert parsed == eid


def test_entry_id_from_concept_returns_none_for_non_notebook() -> None:
    assert entry_id_from_concept("lesson:rag") is None
    assert entry_id_from_concept("anything") is None


def test_entry_id_from_concept_returns_none_for_garbage_uuid() -> None:
    assert entry_id_from_concept("notebook:not-a-uuid") is None
    assert entry_id_from_concept("notebook:") is None


def test_all_tags_returns_sorted_distinct_display_strings() -> None:
    e1 = NotebookEntry(
        id=uuid.uuid4(), user_id=uuid.uuid4(),
        message_id="a", conversation_id="c", content="x",
        tags=["Python", "RAG", "  "],
    )
    e2 = NotebookEntry(
        id=uuid.uuid4(), user_id=uuid.uuid4(),
        message_id="b", conversation_id="c", content="y",
        tags=["python", "Async", ""],  # 'python' dedupes against 'Python'
    )
    e3 = NotebookEntry(
        id=uuid.uuid4(), user_id=uuid.uuid4(),
        message_id="c", conversation_id="c", content="z",
        tags=None,  # None must be tolerated
    )
    out = all_tags([e1, e2, e3])
    # Sorted case-insensitive; first-seen casing wins for dedupes.
    assert out == ["Async", "Python", "RAG"]


def test_all_tags_handles_empty_iterable() -> None:
    assert all_tags([]) == []


# ---------------------------------------------------------------------------
# DB tests — fixtures
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession, email: str = "nb@test.dev"
) -> User:
    u = User(email=email, full_name="Notebook User", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_entry(
    db: AsyncSession,
    *,
    user: User,
    content: str,
    source: str = "chat",
    tags: list[str] | None = None,
    graduated_at: datetime | None = None,
) -> NotebookEntry:
    e = NotebookEntry(
        user_id=user.id,
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
        conversation_id="conv-1",
        content=content,
        source_type=source,
        tags=list(tags or []),
        graduated_at=graduated_at,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e


# ---------------------------------------------------------------------------
# list_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_user_returns_all_when_no_filters(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    await _make_entry(db_session, user=user, content="A")
    await _make_entry(db_session, user=user, content="B")

    rows = await list_for_user(db_session, user_id=user.id)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_list_for_user_filters_by_source(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    await _make_entry(db_session, user=user, content="from chat", source="chat")
    await _make_entry(db_session, user=user, content="from quiz", source="quiz")

    chat_rows = await list_for_user(db_session, user_id=user.id, source="chat")
    quiz_rows = await list_for_user(db_session, user_id=user.id, source="quiz")
    assert len(chat_rows) == 1
    assert chat_rows[0].source_type == "chat"
    assert len(quiz_rows) == 1
    assert quiz_rows[0].source_type == "quiz"


@pytest.mark.asyncio
async def test_list_for_user_filters_by_graduated(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    grad_at = datetime.now(UTC) - timedelta(hours=1)
    await _make_entry(db_session, user=user, content="grad", graduated_at=grad_at)
    await _make_entry(db_session, user=user, content="open")
    await _make_entry(db_session, user=user, content="open2")

    all_rows = await list_for_user(db_session, user_id=user.id, graduated="all")
    grad_rows = await list_for_user(
        db_session, user_id=user.id, graduated="graduated"
    )
    open_rows = await list_for_user(
        db_session, user_id=user.id, graduated="in_review"
    )
    assert len(all_rows) == 3
    assert len(grad_rows) == 1
    assert grad_rows[0].graduated_at is not None
    assert len(open_rows) == 2
    assert all(r.graduated_at is None for r in open_rows)


@pytest.mark.asyncio
async def test_list_for_user_filters_by_tag_case_insensitive(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    await _make_entry(db_session, user=user, content="tag1", tags=["RAG", "Python"])
    await _make_entry(db_session, user=user, content="tag2", tags=["async"])
    await _make_entry(db_session, user=user, content="untagged")

    rag_rows = await list_for_user(db_session, user_id=user.id, tag="rag")
    assert len(rag_rows) == 1
    assert rag_rows[0].content == "tag1"

    # Empty / whitespace-only tag is no-op (returns all).
    blank_rows = await list_for_user(db_session, user_id=user.id, tag="   ")
    assert len(blank_rows) == 3


@pytest.mark.asyncio
async def test_list_for_user_orders_newest_first(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    first = await _make_entry(db_session, user=user, content="older")
    second = await _make_entry(db_session, user=user, content="newer")
    rows = await list_for_user(db_session, user_id=user.id)
    assert rows[0].id == second.id
    assert rows[1].id == first.id


# ---------------------------------------------------------------------------
# summary_for_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_for_user_empty(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    summary = await summary_for_user(db_session, user=user)
    assert isinstance(summary, NotebookSummary)
    assert summary.total == 0
    assert summary.graduated == 0
    assert summary.in_review == 0
    assert summary.by_source == []
    assert summary.latest_graduated_at is None
    assert summary.graduation_percentage == 0.0


@pytest.mark.asyncio
async def test_summary_for_user_aggregates_counts(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    grad_at = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    await _make_entry(db_session, user=user, content="g1",
                      source="chat", graduated_at=grad_at)
    await _make_entry(db_session, user=user, content="i1", source="chat")
    await _make_entry(db_session, user=user, content="q1", source="quiz")

    summary = await summary_for_user(db_session, user=user)
    assert summary.total == 3
    assert summary.graduated == 1
    assert summary.in_review == 2
    assert summary.graduation_percentage == round(1 / 3 * 100, 1)
    assert summary.latest_graduated_at is not None
    by_source = {s.source: s.count for s in summary.by_source}
    assert by_source.get("chat") == 2
    assert by_source.get("quiz") == 1


# ---------------------------------------------------------------------------
# maybe_graduate_card
# ---------------------------------------------------------------------------


async def _make_card(
    db: AsyncSession,
    *,
    user: User,
    concept_key: str,
    repetitions: int = 0,
) -> SRSCard:
    card = SRSCard(
        user_id=user.id,
        concept_key=concept_key,
        prompt="p",
        answer="a",
        hint="h",
        ease_factor=2.5,
        interval_days=0,
        repetitions=repetitions,
        next_due_at=datetime.now(UTC),
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


@pytest.mark.asyncio
async def test_maybe_graduate_card_skips_non_notebook_concept(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    card = await _make_card(
        db_session, user=user, concept_key="lesson:rag", repetitions=10
    )
    out = await maybe_graduate_card(db_session, card=card)
    assert out is None


@pytest.mark.asyncio
async def test_maybe_graduate_card_skips_when_below_threshold(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    entry = await _make_entry(db_session, user=user, content="not yet")
    card = await _make_card(
        db_session,
        user=user,
        concept_key=concept_key_for(entry),
        repetitions=GRADUATION_THRESHOLD_REPS - 1,
    )
    out = await maybe_graduate_card(db_session, card=card)
    assert out is None
    await db_session.refresh(entry)
    assert entry.graduated_at is None


@pytest.mark.asyncio
async def test_maybe_graduate_card_stamps_graduated_at(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    entry = await _make_entry(db_session, user=user, content="ready")
    card = await _make_card(
        db_session,
        user=user,
        concept_key=concept_key_for(entry),
        repetitions=GRADUATION_THRESHOLD_REPS,
    )
    moment = datetime.now(UTC).replace(microsecond=0)
    out = await maybe_graduate_card(db_session, card=card, now=moment)
    assert out is not None
    assert out.graduated_at is not None
    await db_session.refresh(entry)
    assert entry.graduated_at is not None


@pytest.mark.asyncio
async def test_maybe_graduate_card_is_idempotent(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    initial = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    entry = await _make_entry(
        db_session, user=user, content="already", graduated_at=initial
    )
    card = await _make_card(
        db_session,
        user=user,
        concept_key=concept_key_for(entry),
        repetitions=GRADUATION_THRESHOLD_REPS + 5,
    )
    out = await maybe_graduate_card(db_session, card=card)
    assert out is not None
    # The original timestamp must not be overwritten.
    assert out.graduated_at == initial


@pytest.mark.asyncio
async def test_maybe_graduate_card_returns_none_when_entry_missing(
    db_session: AsyncSession,
) -> None:
    """concept_key parses but the entry row was deleted — must not crash."""
    user = await _make_user(db_session)
    fake_id = uuid.uuid4()
    card = await _make_card(
        db_session,
        user=user,
        concept_key=f"{NOTEBOOK_CONCEPT_PREFIX}{fake_id}",
        repetitions=GRADUATION_THRESHOLD_REPS,
    )
    out = await maybe_graduate_card(db_session, card=card)
    assert out is None
