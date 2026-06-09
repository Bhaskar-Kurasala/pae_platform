"""MemoryStore — write, recall, forget, decay.

Postgres-backed (pgvector). Each test gets its own throwaway schema
via the `pg_session` fixture in conftest. If Postgres isn't reachable
the whole module is skipped, so this file co-exists peacefully with
the SQLite suite.

Why we don't use the live `agent_memory` table from the real schema:
the per-test schema is faster, isolates parallel test runs, and lets
us stress the dimension constraints without polluting dev data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives.embeddings import EMBEDDING_DIM, embed_text
from app.agents.primitives.memory import MemoryStore, MemoryWrite

pytestmark = [pytest.mark.asyncio]


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def store(
    pg_session: AsyncSession,
    voyage_disabled: None,
) -> MemoryStore:
    """A MemoryStore bound to the per-test schema with the deterministic
    hash embedder. `voyage_disabled` short-circuits any live Voyage
    calls so the suite is hermetic."""
    return MemoryStore(pg_session)


def _user_id() -> uuid.UUID:
    """Helper for tests — generate a stable-looking user id without
    seeding the users table (the throwaway schema doesn't carry FK
    constraints to it, and our migration leaves user_id nullable)."""
    return uuid.uuid4()


# ── write ───────────────────────────────────────────────────────────


async def test_write_creates_row_with_hash_fallback_embedding(
    store: MemoryStore, pg_session: AsyncSession
) -> None:
    user = _user_id()
    row = await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="learning_coach",
            scope="user",
            key="goal_role",
            value={"role": "Senior GenAI Engineer", "deadline": "2026-09-01"},
        )
    )
    assert row.id is not None
    assert row.embedding is not None
    assert len(row.embedding) == EMBEDDING_DIM
    # Confirm the row landed on disk via a raw count.
    raw = await pg_session.execute(sql_text("SELECT count(*) FROM agent_memory"))
    assert raw.scalar_one() == 1


async def test_write_rejects_wrong_dim_embedding(store: MemoryStore) -> None:
    """An explicit embedding of the wrong dimension should fail at the
    pydantic boundary, not at the DB. Cleaner error message + earlier
    failure point."""
    with pytest.raises(ValueError, match="1536 dimensions"):
        MemoryWrite(
            user_id=_user_id(),
            agent_name="x",
            scope="user",
            key="k",
            value={"v": 1},
            embedding=[0.0] * 1024,  # the trap we're guarding against
        )


async def test_write_is_idempotent_on_repeat_key(
    store: MemoryStore, pg_session: AsyncSession
) -> None:
    """Same (user, agent, scope, key) → update in place, not a second
    row. Otherwise repeated agent runs would balloon the table."""
    user = _user_id()
    base = MemoryWrite(
        user_id=user,
        agent_name="learning_coach",
        scope="user",
        key="preferred_pace",
        value={"hours_per_week": 10},
    )
    first = await store.write(base)
    second = await store.write(
        base.model_copy(update={"value": {"hours_per_week": 12}})
    )
    assert first.id == second.id
    raw = await pg_session.execute(sql_text("SELECT count(*) FROM agent_memory"))
    assert raw.scalar_one() == 1


# ── recall — semantic ───────────────────────────────────────────────


async def test_recall_semantic_returns_similar_row(store: MemoryStore) -> None:
    """The hash fallback isn't a real model, but it IS deterministic.
    A query string identical to the stored key embeds to the same
    vector, so cosine similarity is 1.0 — easy floor for the test."""
    user = _user_id()
    await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="learning_coach",
            scope="user",
            key="priya wants the genai role",
            value={"text": "she said it twice in week one"},
        )
    )
    rows = await store.recall(
        "priya wants the genai role",
        user_id=user,
        agent_name="learning_coach",
        scope="user",
        mode="semantic",
        k=5,
    )
    assert len(rows) == 1
    assert rows[0].similarity is not None and rows[0].similarity > 0.99


async def test_recall_semantic_threshold_filters_unrelated(
    store: MemoryStore,
) -> None:
    """Ensure the threshold actually bites — an unrelated query
    should not surface the row."""
    user = _user_id()
    await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="learning_coach",
            scope="user",
            key="priya wants the genai role",
            value={"v": 1},
        )
    )
    # Pick a query that's far in hash space.
    rows = await store.recall(
        "the eiffel tower is a steel landmark in paris",
        user_id=user,
        agent_name="learning_coach",
        mode="semantic",
        k=5,
        min_similarity=0.4,
    )
    assert rows == []


# ── recall — structured ─────────────────────────────────────────────


async def test_recall_structured_uses_substring_key_match(
    store: MemoryStore,
) -> None:
    user = _user_id()
    await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="learning_coach",
            scope="user",
            key="goal_role:senior_genai",
            value={"target": "Senior GenAI Engineer"},
        )
    )
    rows = await store.recall(
        "GOAL_ROLE",  # uppercase to test case-insensitivity
        user_id=user,
        mode="structured",
        k=5,
    )
    assert len(rows) == 1
    # Structured rows do not carry a similarity score.
    assert rows[0].similarity is None


# ── recall — hybrid ─────────────────────────────────────────────────


async def test_recall_hybrid_dedups_and_orders_by_similarity_first(
    store: MemoryStore,
) -> None:
    """Hybrid mode runs both branches and dedupes by id. Rows with a
    similarity score sort ahead of structured-only rows; that ordering
    is what surfaces the most relevant memory first when both modes
    fire on the same key."""
    user = _user_id()
    await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="learning_coach",
            scope="user",
            key="goal_role:priya",
            value={"role": "GenAI Engineer"},
        )
    )
    rows = await store.recall(
        "goal_role:priya",
        user_id=user,
        mode="hybrid",
        k=5,
    )
    # Single source row — both branches hit, but dedup yields one.
    assert len(rows) == 1
    # And it should carry a similarity score (semantic branch found it).
    assert rows[0].similarity is not None


# ── recall — scope filtering ────────────────────────────────────────


async def test_recall_user_scope_isolates_users(store: MemoryStore) -> None:
    """User-scoped memories must NEVER leak between users.

    This is the load-bearing privacy assertion for the whole memory
    layer — if it ever flips, every prompt-injection vector that
    leaks one student's memory to another student becomes live.
    """
    alice = _user_id()
    bob = _user_id()
    for u in (alice, bob):
        await store.write(
            MemoryWrite(
                user_id=u,
                agent_name="coach",
                scope="user",
                key="secret",
                value={"plan": f"private to {u}"},
            )
        )
    rows = await store.recall(
        "secret",
        user_id=alice,
        scope="user",
        mode="hybrid",
        k=10,
    )
    assert len(rows) == 1
    assert rows[0].user_id == alice


async def test_recall_global_scope_is_visible_to_any_user(
    store: MemoryStore,
) -> None:
    """Global memories are platform-wide context (e.g. "students prefer
    morning emails"). Any user query must surface them."""
    await store.write(
        MemoryWrite(
            user_id=None,
            agent_name="coach",
            scope="global",
            key="best_outreach_time",
            value={"hour_utc": 14},
        )
    )
    user = _user_id()
    rows = await store.recall(
        "best_outreach_time",
        user_id=user,
        mode="hybrid",
        k=5,
    )
    assert len(rows) == 1
    assert rows[0].scope == "global"


# ── recall — touch (access count + last_used_at) ────────────────────


async def test_recall_increments_access_count(
    store: MemoryStore, pg_session: AsyncSession
) -> None:
    user = _user_id()
    written = await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="coach",
            scope="user",
            key="ping",
            value={"v": 1},
        )
    )
    await store.recall("ping", user_id=user, mode="structured", k=5)
    await store.recall("ping", user_id=user, mode="structured", k=5)

    raw = await pg_session.execute(
        sql_text(
            "SELECT access_count FROM agent_memory WHERE id = :id"
        ),
        {"id": written.id},
    )
    assert raw.scalar_one() == 2


# ── forget ──────────────────────────────────────────────────────────


async def test_forget_removes_a_known_id(
    store: MemoryStore, pg_session: AsyncSession
) -> None:
    user = _user_id()
    row = await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="coach",
            scope="user",
            key="x",
            value={"v": 1},
        )
    )
    removed = await store.forget(row.id)
    assert removed is True
    raw = await pg_session.execute(sql_text("SELECT count(*) FROM agent_memory"))
    assert raw.scalar_one() == 0


async def test_forget_returns_false_for_unknown_id(store: MemoryStore) -> None:
    removed = await store.forget(uuid.uuid4())
    assert removed is False


# ── decay ───────────────────────────────────────────────────────────


async def test_decay_lowers_confidence_for_idle_rows(
    store: MemoryStore, pg_session: AsyncSession
) -> None:
    """Rows untouched for >= idle_window get their confidence
    multiplied. Touched rows are exempt — exactly the contract
    `recall()`'s _touch step relies on."""
    user = _user_id()
    fresh = await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="coach",
            scope="user",
            key="fresh",
            value={"v": 1},
            confidence=1.0,
        )
    )
    stale = await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="coach",
            scope="user",
            key="stale",
            value={"v": 1},
            confidence=1.0,
        )
    )
    # Backdate the stale row's last_used_at by 30 days.
    await pg_session.execute(
        sql_text(
            "UPDATE agent_memory "
            "SET last_used_at = :ts WHERE id = :id"
        ),
        {
            "ts": datetime.now(UTC) - timedelta(days=30),
            "id": stale.id,
        },
    )
    await pg_session.commit()

    counts = await store.decay(idle_window_days=14, confidence_multiplier=0.9)
    assert counts["decayed"] >= 1

    # Reload both rows.
    raw = await pg_session.execute(
        sql_text(
            "SELECT id, confidence FROM agent_memory ORDER BY key"
        )
    )
    by_id = {r[0]: float(r[1]) for r in raw.all()}
    assert by_id[fresh.id] == pytest.approx(1.0)
    # Stale row decayed; allow a wide tolerance because confidence
    # may be multiplied multiple times in the same pass if we ever
    # add iterative decay.
    assert by_id[stale.id] < 1.0


async def test_decay_deletes_rows_below_threshold(
    store: MemoryStore, pg_session: AsyncSession
) -> None:
    user = _user_id()
    row = await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="coach",
            scope="user",
            key="dying",
            value={"v": 1},
            confidence=0.05,  # already below default delete_below=0.10
        )
    )
    counts = await store.decay()
    assert counts["deleted"] >= 1
    raw = await pg_session.execute(
        sql_text("SELECT count(*) FROM agent_memory WHERE id = :id"),
        {"id": row.id},
    )
    assert raw.scalar_one() == 0


async def test_decay_drops_expired_rows(
    store: MemoryStore, pg_session: AsyncSession
) -> None:
    user = _user_id()
    row = await store.write(
        MemoryWrite(
            user_id=user,
            agent_name="coach",
            scope="user",
            key="ephemeral",
            value={"v": 1},
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    counts = await store.decay()
    assert counts["expired"] >= 1
    raw = await pg_session.execute(
        sql_text("SELECT count(*) FROM agent_memory WHERE id = :id"),
        {"id": row.id},
    )
    assert raw.scalar_one() == 0


# ── 100-memory recall stress (spec) ─────────────────────────────────


async def test_recall_top_k_relevance_with_100_memories(
    store: MemoryStore,
) -> None:
    """Spec asks for: write 100 memories, recall, assert top-k
    relevance. We seed 100 distinct user-scoped memories, then issue
    a query identical to one of them and assert that target ranks
    first."""
    user = _user_id()
    target_key = "priya finishes capstone by friday"
    for i in range(100):
        key = target_key if i == 42 else f"unrelated fact number {i}"
        await store.write(
            MemoryWrite(
                user_id=user,
                agent_name="coach",
                scope="user",
                key=key,
                value={"i": i},
            )
        )
    rows = await store.recall(
        target_key,
        user_id=user,
        mode="semantic",
        k=5,
    )
    assert rows, "expected at least one semantic hit out of 100 rows"
    # The deterministic hash fallback gives an *exact* match a
    # similarity of 1.0; the target row should be #1.
    assert rows[0].key == target_key
    assert rows[0].similarity is not None and rows[0].similarity > 0.99


# ── helpers (sanity check the embedder behaves) ─────────────────────


async def test_embed_text_in_test_environment_returns_dim() -> None:
    vec = await embed_text("smoke test")
    assert len(vec) == EMBEDDING_DIM
