"""Unit tests for scaffolding-decay (P2-01).

Covers the pure classification + decay logic so we don't depend on DB state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.services.scaffolding_service import (
    DECAY_AFTER_DAYS,
    DECAY_FACTOR,
    compute_level,
    load_level,
)


def test_novice_gets_high_scaffolding() -> None:
    result = compute_level(0.0, None)
    assert result.label == "high"
    assert result.decayed is False
    assert "novice" in result.prompt_fragment.lower()


def test_intermediate_gets_medium_scaffolding() -> None:
    now = datetime.now(UTC)
    result = compute_level(0.5, now, now=now)
    assert result.label == "medium"
    assert result.decayed is False


def test_competent_gets_low_scaffolding() -> None:
    now = datetime.now(UTC)
    result = compute_level(0.85, now, now=now)
    assert result.label == "low"
    assert result.decayed is False
    assert "do not provide" in result.prompt_fragment.lower()


def test_decay_applies_after_window() -> None:
    now = datetime(2026, 4, 18, tzinfo=UTC)
    stale = now - timedelta(days=DECAY_AFTER_DAYS + 1)
    # raw 0.85 * 0.7 = 0.595 → medium, not low
    result = compute_level(0.85, stale, now=now)
    assert result.decayed is True
    assert result.label == "medium"
    assert result.effective_confidence == pytest.approx(0.85 * DECAY_FACTOR)


def test_decay_does_not_apply_within_window() -> None:
    now = datetime(2026, 4, 18, tzinfo=UTC)
    recent = now - timedelta(days=DECAY_AFTER_DAYS - 1)
    result = compute_level(0.85, recent, now=now)
    assert result.decayed is False
    assert result.label == "low"


def test_naive_datetime_is_treated_as_utc() -> None:
    # SQLite strips tzinfo; make sure we don't crash comparing naive vs aware.
    now = datetime(2026, 4, 18, tzinfo=UTC)
    stale_naive = (now - timedelta(days=30)).replace(tzinfo=None)
    result = compute_level(0.5, stale_naive, now=now)
    assert result.decayed is True


def test_confidence_is_clamped() -> None:
    assert compute_level(-0.2, None).effective_confidence == 0.0
    assert compute_level(1.5, None).effective_confidence == 1.0


@pytest.mark.asyncio
async def test_load_level_missing_state_is_novice(db_session: AsyncSession) -> None:
    user = User(email="scaffold@test.dev", full_name="S", role="student")
    skill = Skill(slug="attention", name="Attention", description="", difficulty=3)
    db_session.add_all([user, skill])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(skill)

    result = await load_level(db_session, user.id, skill.id)
    assert result.label == "high"
    assert result.raw_confidence == 0.0


@pytest.mark.asyncio
async def test_load_level_reads_existing_state(db_session: AsyncSession) -> None:
    user = User(email="scaffold2@test.dev", full_name="S", role="student")
    skill = Skill(slug="transformers", name="Transformers", description="", difficulty=4)
    db_session.add_all([user, skill])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(skill)

    now = datetime.now(UTC)
    db_session.add(
        UserSkillState(
            user_id=user.id,
            skill_id=skill.id,
            mastery_level="proficient",
            confidence=0.8,
            last_touched_at=now,
        )
    )
    await db_session.commit()

    result = await load_level(db_session, user.id, skill.id)
    assert result.raw_confidence == 0.8
    assert result.label == "low"
    assert result.decayed is False


@pytest.mark.asyncio
async def test_load_level_nonexistent_skill_returns_novice(db_session: AsyncSession) -> None:
    user = User(email="scaffold3@test.dev", full_name="S", role="student")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    result = await load_level(db_session, user.id, uuid.uuid4())
    assert result.label == "high"
    assert result.raw_confidence == 0.0
