"""End-to-end test: an SRSService.review() call that crosses the rep
threshold for a notebook-backed card stamps `graduated_at` on the entry
(Notebook + Tutor refactor 2026-04-26).

Also asserts idempotence — a second review call after graduation must NOT
move the timestamp.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notebook_entry import NotebookEntry
from app.models.srs_card import SRSCard
from app.models.user import User
from app.services.notebook_service import (
    GRADUATION_THRESHOLD_REPS,
    concept_key_for,
)
from app.services.srs_service import SRSService


async def _make_user(db: AsyncSession) -> User:
    u = User(
        email="srs-grad@test.dev", full_name="SRS Grad", role="student"
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_entry(db: AsyncSession, *, user: User) -> NotebookEntry:
    e = NotebookEntry(
        user_id=user.id,
        message_id="msg-grad",
        conversation_id="conv-grad",
        content="Vector cosine returns -1..1.",
        tags=[],
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e


async def _make_card(
    db: AsyncSession,
    *,
    user: User,
    entry: NotebookEntry,
    repetitions: int,
    interval_days: int,
) -> SRSCard:
    card = SRSCard(
        user_id=user.id,
        concept_key=concept_key_for(entry),
        prompt="What does cosine return?",
        answer="-1..1",
        hint="bounded range",
        ease_factor=2.5,
        interval_days=interval_days,
        repetitions=repetitions,
        next_due_at=datetime.now(UTC),
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


@pytest.mark.asyncio
async def test_review_crossing_threshold_graduates_entry(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    entry = await _make_entry(db_session, user=user)
    card = await _make_card(
        db_session,
        user=user,
        entry=entry,
        repetitions=GRADUATION_THRESHOLD_REPS - 1,
        interval_days=1,
    )

    svc = SRSService(db_session)
    reviewed = await svc.review(
        user_id=user.id, card_id=card.id, quality=4
    )
    # SM-2 bumps repetitions from 1 → 2.
    assert reviewed.repetitions == GRADUATION_THRESHOLD_REPS

    await db_session.refresh(entry)
    assert entry.graduated_at is not None


@pytest.mark.asyncio
async def test_second_review_after_graduation_is_idempotent(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    entry = await _make_entry(db_session, user=user)
    card = await _make_card(
        db_session,
        user=user,
        entry=entry,
        repetitions=GRADUATION_THRESHOLD_REPS - 1,
        interval_days=1,
    )

    svc = SRSService(db_session)
    await svc.review(user_id=user.id, card_id=card.id, quality=4)
    await db_session.refresh(entry)
    first_stamp = entry.graduated_at
    assert first_stamp is not None

    # Drive another successful review — repetitions go to 3, but graduated_at
    # must NOT shift.
    await svc.review(user_id=user.id, card_id=card.id, quality=5)
    await db_session.refresh(entry)
    assert entry.graduated_at == first_stamp
