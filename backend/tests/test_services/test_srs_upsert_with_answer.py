"""Tests for SRSService.upsert_card answer/hint backfill semantics.

The Today refactor added `answer` and `hint` to SRS cards. The upsert helper
must:
- persist answer/hint on first insert
- only fill blank fields on subsequent calls (never overwrite curated copy)
- keep prior SM-2 state untouched (fresh inserts use defaults)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.srs_service import DEFAULT_EASE, SRSService


async def _make_user(
    db: AsyncSession, email: str = "srs-up@test.dev"
) -> User:
    u = User(email=email, full_name="SRS Upsert", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_upsert_persists_answer_and_hint_on_create(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    svc = SRSService(db_session)
    card = await svc.upsert_card(
        user_id=user.id,
        concept_key="lesson:rag",
        prompt="What is RAG?",
        answer="Retrieval-augmented generation",
        hint="It augments generation with...",
    )
    assert card.prompt == "What is RAG?"
    assert card.answer == "Retrieval-augmented generation"
    assert card.hint == "It augments generation with..."
    assert card.repetitions == 0
    assert card.interval_days == 0
    assert card.ease_factor == DEFAULT_EASE


@pytest.mark.asyncio
async def test_upsert_existing_card_only_fills_blank_fields(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    svc = SRSService(db_session)

    # First insert: only prompt populated.
    first = await svc.upsert_card(
        user_id=user.id, concept_key="lesson:embed", prompt="Embeddings?"
    )
    assert first.answer == ""
    assert first.hint == ""

    # Second call backfills the empty answer/hint.
    second = await svc.upsert_card(
        user_id=user.id,
        concept_key="lesson:embed",
        prompt="Different prompt — should NOT overwrite",
        answer="Vector representations of text",
        hint="They live in a high-dimensional space",
    )
    assert second.id == first.id  # same row
    assert second.prompt == "Embeddings?"  # original kept
    assert second.answer == "Vector representations of text"
    assert second.hint == "They live in a high-dimensional space"


@pytest.mark.asyncio
async def test_upsert_does_not_overwrite_existing_answer(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    svc = SRSService(db_session)
    await svc.upsert_card(
        user_id=user.id,
        concept_key="lesson:tokens",
        prompt="Tokens?",
        answer="Sub-word units",
        hint="Think BPE",
    )
    # Re-upsert with new copy — must NOT clobber.
    again = await svc.upsert_card(
        user_id=user.id,
        concept_key="lesson:tokens",
        prompt="Tokens? (v2)",
        answer="WORDS",
        hint="HINT2",
    )
    assert again.answer == "Sub-word units"
    assert again.hint == "Think BPE"


@pytest.mark.asyncio
async def test_upsert_existing_card_preserves_sm2_state(
    db_session: AsyncSession,
) -> None:
    """Re-running upsert must not reset interval/repetitions after a real review."""
    user = await _make_user(db_session)
    svc = SRSService(db_session)
    card = await svc.upsert_card(
        user_id=user.id, concept_key="lesson:async", prompt="async/await"
    )
    # Simulate a successful SM-2 step having advanced state.
    reviewed = await svc.review(
        user_id=user.id, card_id=card.id, quality=5
    )
    assert reviewed.repetitions == 1
    assert reviewed.interval_days == 1

    # Calling upsert again should not touch SM-2 fields.
    same = await svc.upsert_card(
        user_id=user.id,
        concept_key="lesson:async",
        prompt="ignored",
        answer="now-with-answer",
    )
    assert same.id == card.id
    assert same.repetitions == 1
    assert same.interval_days == 1
    assert same.answer == "now-with-answer"


@pytest.mark.asyncio
async def test_upsert_separates_cards_per_user(db_session: AsyncSession) -> None:
    a = await _make_user(db_session, "a-srs@test.dev")
    b = await _make_user(db_session, "b-srs@test.dev")
    svc = SRSService(db_session)
    ca = await svc.upsert_card(
        user_id=a.id, concept_key="shared", prompt="A", answer="ans-a"
    )
    cb = await svc.upsert_card(
        user_id=b.id, concept_key="shared", prompt="B", answer="ans-b"
    )
    assert ca.id != cb.id
    assert ca.answer == "ans-a"
    assert cb.answer == "ans-b"


@pytest.mark.asyncio
async def test_upsert_with_blank_answer_leaves_card_answer_blank(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    svc = SRSService(db_session)
    card = await svc.upsert_card(
        user_id=user.id, concept_key="bare", prompt="bare-prompt"
    )
    assert card.answer == ""
    assert card.hint == ""


@pytest.mark.asyncio
async def test_upsert_review_lookup_failure_for_unknown_card_id(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    svc = SRSService(db_session)
    with pytest.raises(LookupError):
        await svc.review(user_id=user.id, card_id=uuid.uuid4(), quality=4)
