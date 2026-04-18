"""Cross-session integration test for conversation memory (P3 3A-2).

Conversation 1 upserts a memory; conversation 2 loads it and sees it
rendered inside the student-context block. Exercises the real DB path
through the in-memory SQLite fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.user import User
from app.services.conversation_memory_service import (
    load_recent_memories,
    upsert_memory,
)
from app.services.student_context_service import build_context_block


async def _make_user(db: AsyncSession) -> User:
    u = User(email="memory@t.test", full_name="Mem Test", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_skill(db: AsyncSession, slug: str, name: str) -> Skill:
    s = Skill(name=name, slug=slug, description="d", difficulty=1)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest.mark.asyncio
async def test_memory_written_then_loaded_next_session(
    db_session: AsyncSession,
) -> None:
    """Core cross-session contract: conv-1 writes, conv-2 reads."""
    user = await _make_user(db_session)
    skill = await _make_skill(db_session, "rag", "Retrieval-Augmented Generation")

    # Conversation 1 — end of turn, tutor commits a memory summary.
    t1 = datetime(2026, 4, 18, 10, 0, tzinfo=UTC)
    await upsert_memory(
        db_session,
        user.id,
        skill.id,
        "Covered chunking strategies; student confused fixed vs semantic.",
        now=t1,
    )
    await db_session.commit()

    # Conversation 2 — five hours later, new session opens.
    t2 = t1 + timedelta(hours=5)
    memories = await load_recent_memories(db_session, user.id, now=t2)
    assert len(memories) == 1
    assert memories[0].skill_slug == "rag"
    assert memories[0].age_hours == 5
    assert "chunking" in memories[0].summary_text


@pytest.mark.asyncio
async def test_upsert_overwrites_existing_row(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    skill = await _make_skill(db_session, "prompting", "Prompting")

    t1 = datetime(2026, 4, 18, 9, 0, tzinfo=UTC)
    await upsert_memory(db_session, user.id, skill.id, "first draft", now=t1)
    await db_session.commit()

    t2 = t1 + timedelta(hours=2)
    await upsert_memory(
        db_session, user.id, skill.id, "refined understanding", now=t2
    )
    await db_session.commit()

    memories = await load_recent_memories(db_session, user.id, now=t2)
    assert len(memories) == 1
    assert memories[0].summary_text == "refined understanding"
    assert memories[0].age_hours == 0


@pytest.mark.asyncio
async def test_load_caps_at_limit_and_orders_fresh_first(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    base = datetime(2026, 4, 18, 10, 0, tzinfo=UTC)
    # Write 7 memories across different skills, then load with limit=5.
    for i in range(7):
        skill = await _make_skill(db_session, f"s{i}", f"Skill {i}")
        await upsert_memory(
            db_session,
            user.id,
            skill.id,
            f"summary {i}",
            now=base - timedelta(hours=i),  # i=0 freshest, i=6 oldest
        )
    await db_session.commit()

    memories = await load_recent_memories(db_session, user.id, limit=5, now=base)
    assert len(memories) == 5
    # Freshest first: skills 0..4 in that order.
    slugs = [m.skill_slug for m in memories]
    assert slugs == ["s0", "s1", "s2", "s3", "s4"]


@pytest.mark.asyncio
async def test_context_block_contains_memory_line(
    db_session: AsyncSession,
) -> None:
    """build_context_block must surface memory as a render line."""
    user = await _make_user(db_session)
    skill = await _make_skill(db_session, "embeddings", "Embeddings")

    t1 = datetime(2026, 4, 18, 10, 0, tzinfo=UTC)
    await upsert_memory(
        db_session,
        user.id,
        skill.id,
        "discussed cosine vs dot product",
        now=t1,
    )
    await db_session.commit()

    t2 = t1 + timedelta(hours=3)
    block, missing = await build_context_block(db_session, user.id, now=t2)
    assert "Embeddings" in block
    assert "cosine" in block
    assert "3h ago" in block
    assert "memories" not in missing


@pytest.mark.asyncio
async def test_empty_memories_flagged_in_missing(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    t1 = datetime(2026, 4, 18, 10, 0, tzinfo=UTC)
    _, missing = await build_context_block(db_session, user.id, now=t1)
    assert "memories" in missing


@pytest.mark.asyncio
async def test_dangling_skill_memory_is_skipped(
    db_session: AsyncSession,
) -> None:
    """A memory whose skill row was deleted must not appear in loaded output."""
    user = await _make_user(db_session)
    skill = await _make_skill(db_session, "vectors", "Vectors")

    t1 = datetime(2026, 4, 18, 10, 0, tzinfo=UTC)
    await upsert_memory(db_session, user.id, skill.id, "early notes", now=t1)
    await db_session.commit()

    # ON DELETE CASCADE is declared on the FK, but aiosqlite doesn't enforce
    # foreign keys by default. To simulate a dangling memory row we manually
    # null-out the skill map by deleting the skill via ORM — the cascade may
    # or may not fire depending on sqlite PRAGMA. Either way, the loader must
    # not crash: if the row is cascaded away, `memories` is empty; if it
    # lingers, the loader skips it.
    await db_session.delete(skill)
    await db_session.commit()

    t2 = t1 + timedelta(hours=1)
    memories = await load_recent_memories(db_session, user.id, now=t2)
    assert memories == []
