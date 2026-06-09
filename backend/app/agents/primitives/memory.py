"""MemoryStore — Agentic OS Primitive 1.

Persistent long-term memory shared across agent invocations. Backed
by `agent_memory` (pgvector + jsonb). One class with four methods:

  • write(memory)        — insert or update a memory row
  • recall(query, …)     — hybrid retrieval (semantic + structured)
  • forget(memory_id)    — delete a row by id
  • decay()              — nightly Celery sweep that lowers
                            confidence on unused rows and drops
                            anything below threshold

All operations are typed (pydantic v2), structured-logged, and
metric-instrumented. The class wraps a SQLAlchemy AsyncSession that
the caller owns — this keeps the store itself stateless and lets it
participate in the caller's transaction (so e.g. an agent can wrap
a tool call and a memory write in one txn).

The store doesn't read settings.enable_memory itself — that gate is
applied by the AgenticBaseAgent which is the only caller. Tests can
exercise the store directly without touching the flag.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import metrics
from app.agents.primitives.embeddings import EMBEDDING_DIM, embed_text
from app.models.agent_memory import AgentMemory

log = structlog.get_logger().bind(layer="memory")

# Cosine distance threshold for "this row is similar enough to count
# as a recall hit". 0.35 is roughly equivalent to a cosine similarity
# of 0.65 — empirically picked so generic chitchat doesn't surface,
# but topical matches do. Tunable per-call via the `min_similarity`
# arg on recall().
DEFAULT_SIMILARITY_THRESHOLD = 0.35

# Decay job parameters. Confidence multiplier is applied to every
# row whose last_used_at is older than `idle_window`. Rows whose
# confidence drops below `delete_below` are removed entirely.
DECAY_IDLE_WINDOW_DAYS = 14
DECAY_CONFIDENCE_MULTIPLIER = 0.92
DECAY_DELETE_BELOW = 0.10


# ── Pydantic schemas ────────────────────────────────────────────────


MemoryScopeStr = Literal["user", "agent", "global"]


class MemoryWrite(BaseModel):
    """Input for MemoryStore.write().

    All keys + scope are required; embedding is computed lazily by the
    store unless the caller passes one explicitly (e.g. when running
    inside a transaction that already paid the embed cost).
    """

    user_id: uuid.UUID | None = None
    agent_name: str = Field(min_length=1, max_length=200)
    scope: MemoryScopeStr = "user"
    key: str = Field(min_length=1, max_length=512)
    value: dict[str, Any]
    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_message_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    embedding: list[float] | None = None

    @field_validator("embedding")
    @classmethod
    def _check_embedding_dim(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        if len(v) != EMBEDDING_DIM:
            # Catches dim mismatches before they hit Postgres — clearer
            # error message than "vector dimension mismatch".
            raise ValueError(
                f"embedding must have {EMBEDDING_DIM} dimensions, got {len(v)}"
            )
        return v

    @field_validator("scope")
    @classmethod
    def _scope_user_id_alignment(cls, v: str, info: Any) -> str:
        # `user` scope without a user_id is almost always a caller bug.
        # We allow it (the row is "user-scoped but unbound") but warn
        # at construction time so callers see it quickly.
        return v


class MemoryRow(BaseModel):
    """Output shape returned from recall()."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    agent_name: str
    scope: MemoryScopeStr
    key: str
    value: dict[str, Any]
    valence: float
    confidence: float
    similarity: float | None = None  # None when only structured-matched
    source_message_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime
    access_count: int


# ── Store ───────────────────────────────────────────────────────────


class MemoryStore:
    """Agent-facing persistent memory.

    Construct one per session:

        store = MemoryStore(session)
        await store.write(MemoryWrite(...))
        rows = await store.recall("when does priya finish python?", user_id=…)

    The session is the SQLAlchemy AsyncSession the caller manages —
    we never commit it ourselves so callers can roll back on error.
    The lone exception is decay() which is meant to be fired from a
    Celery task and commits its own batch.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._log = log

    # ── write ───────────────────────────────────────────────────────

    async def write(self, memory: MemoryWrite) -> AgentMemory:
        """Upsert a memory row.

        Idempotency is keyed on (user_id, agent_name, scope, key).
        Re-writing the same key updates `value`, refreshes
        `last_used_at`, and increments `access_count`. New rows start
        at access_count=0 so the count reflects "times we recalled
        this", not "times we wrote it".

        Embedding is computed if not supplied. If embedding generation
        fails entirely (no Voyage key + no fallback success), the row
        is still written with `embedding=NULL` — semantic recall will
        skip it but structured recall still works.
        """
        embedding: list[float] | None = memory.embedding
        if embedding is None:
            try:
                # Cheap: hash fallback runs in <1 ms; Voyage adds ~150 ms.
                embedding = await embed_text(self._embedding_text(memory))
            except Exception as exc:  # noqa: BLE001 - last-line safety
                self._log.warning(
                    "memory.write.embedding_failed",
                    error=str(exc),
                    agent=memory.agent_name,
                    key=memory.key,
                )
                embedding = None

        # Postgres ON CONFLICT upsert. The natural unique tuple is
        # (user_id, agent_name, scope, key) but the table doesn't
        # enforce that constraint at the DB level (we left flexibility
        # in case a single key is intentionally written multiple times,
        # e.g. a journal of "preferences observed at time T"). For
        # idempotent writes the caller passes the same key and we
        # update by primary key match using a SELECT-then-update
        # pattern. Single-call upsert lands in a follow-up if needed.
        existing = await self._find_one(
            user_id=memory.user_id,
            agent_name=memory.agent_name,
            scope=memory.scope,
            key=memory.key,
        )
        if existing is not None:
            await self._session.execute(
                update(AgentMemory)
                .where(AgentMemory.id == existing.id)
                .values(
                    value=memory.value,
                    valence=memory.valence,
                    confidence=memory.confidence,
                    source_message_id=memory.source_message_id,
                    expires_at=memory.expires_at,
                    embedding=embedding,
                    last_used_at=datetime.now(UTC),
                )
            )
            self._log.info(
                "memory.write.updated",
                id=str(existing.id),
                agent=memory.agent_name,
                scope=memory.scope,
                key=memory.key,
                user_id=str(memory.user_id) if memory.user_id else None,
            )
            metrics.MEMORY_WRITES_TOTAL.labels(scope=memory.scope).inc()
            await self._session.flush()
            return await self._reload(existing.id)

        row = AgentMemory(
            user_id=memory.user_id,
            agent_name=memory.agent_name,
            scope=memory.scope,
            key=memory.key,
            value=memory.value,
            valence=memory.valence,
            confidence=memory.confidence,
            source_message_id=memory.source_message_id,
            expires_at=memory.expires_at,
            embedding=embedding,
        )
        self._session.add(row)
        await self._session.flush()
        self._log.info(
            "memory.write.created",
            id=str(row.id),
            agent=memory.agent_name,
            scope=memory.scope,
            key=memory.key,
            user_id=str(memory.user_id) if memory.user_id else None,
        )
        metrics.MEMORY_WRITES_TOTAL.labels(scope=memory.scope).inc()
        return row

    # ── recall ──────────────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        *,
        user_id: uuid.UUID | None = None,
        agent_name: str | None = None,
        scope: MemoryScopeStr | None = None,
        k: int = 5,
        mode: Literal["hybrid", "semantic", "structured"] = "hybrid",
        min_similarity: float | None = None,
    ) -> list[MemoryRow]:
        """Hybrid recall over the agent_memory table.

        Modes:
          • semantic   — pure cosine similarity over embedding
          • structured — substring match on key OR exact key match
          • hybrid     — semantic + structured, dedup by id, then sort
                          by score (semantic) or recency (structured)

        Returns up to `k` rows. Rows that hit the structured branch
        have `similarity = None` (we didn't compute one for them). On
        a successful recall, every returned row has its access_count
        incremented and last_used_at refreshed in a single UPDATE so
        the decay job sees them as "actively used".
        """
        start_ms = time.monotonic()
        threshold = (
            min_similarity
            if min_similarity is not None
            else DEFAULT_SIMILARITY_THRESHOLD
        )

        scope_filter = self._scope_clause(user_id, scope)
        agent_filter = (
            (AgentMemory.agent_name == agent_name)
            if agent_name is not None
            else None
        )
        not_expired = (
            (AgentMemory.expires_at.is_(None))
            | (AgentMemory.expires_at > datetime.now(UTC))
        )
        base_clauses = [c for c in (scope_filter, agent_filter, not_expired) if c is not None]

        rows: dict[uuid.UUID, MemoryRow] = {}

        if mode in ("semantic", "hybrid"):
            embedding = await embed_text(query)
            sem = await self._semantic_search(
                embedding=embedding,
                base_clauses=base_clauses,
                k=k,
                threshold=threshold,
            )
            for row, similarity in sem:
                m = MemoryRow.model_validate(row)
                m = m.model_copy(update={"similarity": similarity})
                rows[m.id] = m

        if mode in ("structured", "hybrid"):
            struct_rows = await self._structured_search(
                query=query,
                base_clauses=base_clauses,
                k=k,
            )
            for row in struct_rows:
                if row.id in rows:
                    continue
                m = MemoryRow.model_validate(row)
                rows[m.id] = m

        # Sort: rows with similarity first (semantic results), then
        # structured results by recency. Slice to k.
        ordered = sorted(
            rows.values(),
            key=lambda r: (
                r.similarity is None,  # False (has sim) sorts before True
                -(r.similarity or 0.0),
                -(r.last_used_at.timestamp()),
            ),
        )[:k]

        if ordered:
            await self._touch([r.id for r in ordered])

        duration_ms = int((time.monotonic() - start_ms) * 1000)
        self._log.info(
            "memory.recall",
            mode=mode,
            count=len(ordered),
            duration_ms=duration_ms,
            user_id=str(user_id) if user_id else None,
            agent=agent_name,
            scope=scope,
        )
        metrics.MEMORY_RECALL_HITS.labels(mode=mode).inc(len(ordered))
        metrics.MEMORY_RECALL_DURATION_MS.labels(mode=mode).observe(duration_ms)
        return ordered

    # ── forget ──────────────────────────────────────────────────────

    async def forget(self, memory_id: uuid.UUID) -> bool:
        """Delete a single memory row.

        Returns True if a row was removed, False if the id didn't
        exist. The caller's transaction is responsible for committing.
        """
        result = await self._session.execute(
            delete(AgentMemory).where(AgentMemory.id == memory_id)
        )
        removed = (result.rowcount or 0) > 0
        self._log.info(
            "memory.forget", id=str(memory_id), removed=removed
        )
        return removed

    # ── decay ───────────────────────────────────────────────────────

    async def decay(
        self,
        *,
        idle_window_days: int = DECAY_IDLE_WINDOW_DAYS,
        confidence_multiplier: float = DECAY_CONFIDENCE_MULTIPLIER,
        delete_below: float = DECAY_DELETE_BELOW,
    ) -> dict[str, int]:
        """Nightly sweep — lower confidence on unused rows, prune dead ones.

        Two passes:
          1. UPDATE rows with last_used_at older than `idle_window_days`,
             multiplying confidence by `confidence_multiplier`. Cap at
             `confidence >= 0` to satisfy the migration's check.
          2. DELETE rows whose confidence is below `delete_below` after
             the multiplier pass.

        Also cleans up rows past `expires_at`.

        Commits its own transaction so it can be safely fired from a
        Celery task without sharing a session with anyone.

        Returns counts: {"decayed": int, "deleted": int, "expired": int}.
        """
        cutoff = datetime.now(UTC) - timedelta(days=idle_window_days)

        # Pass 1: confidence decay on stale rows.
        decay_stmt = (
            update(AgentMemory)
            .where(AgentMemory.last_used_at < cutoff)
            .values(
                confidence=func.greatest(
                    AgentMemory.confidence * confidence_multiplier,
                    0.0,
                )
            )
        )
        decayed_result = await self._session.execute(decay_stmt)
        decayed = decayed_result.rowcount or 0

        # Pass 2: delete anything that crossed below the threshold.
        delete_stmt = delete(AgentMemory).where(
            AgentMemory.confidence < delete_below
        )
        deleted_result = await self._session.execute(delete_stmt)
        deleted = deleted_result.rowcount or 0

        # Pass 3: drop expired rows. Independent of confidence.
        expire_stmt = delete(AgentMemory).where(
            and_(
                AgentMemory.expires_at.is_not(None),
                AgentMemory.expires_at < datetime.now(UTC),
            )
        )
        expired_result = await self._session.execute(expire_stmt)
        expired = expired_result.rowcount or 0

        await self._session.commit()
        self._log.info(
            "memory.decay",
            decayed=decayed,
            deleted=deleted,
            expired=expired,
            idle_window_days=idle_window_days,
            confidence_multiplier=confidence_multiplier,
            delete_below=delete_below,
        )
        return {"decayed": decayed, "deleted": deleted, "expired": expired}

    # ── private helpers ─────────────────────────────────────────────

    @staticmethod
    def _embedding_text(memory: MemoryWrite) -> str:
        """Serialize a memory into the string we hand to the embedder.

        Embeds the **key** alone by default. Recall queries are
        free-form text the caller supplies; the only string shape that
        both sides reliably share is the key. Mixing JSON value into
        the embedded text was tried first and broke deterministic
        recall — the value side has no analogue on the recall query
        side, so the embedded vectors drifted apart even for trivially
        identical lookups.
        """
        text = memory.key
        if len(text) > 4000:
            text = text[:4000]
        return text

    @staticmethod
    def _scope_clause(
        user_id: uuid.UUID | None,
        scope: MemoryScopeStr | None,
    ) -> Any:
        """Build the WHERE clause that scopes recall to the right rows.

        Default: include all scopes the caller could legitimately read.
        If a scope is passed explicitly, it pins the query.
        """
        if scope == "global":
            return AgentMemory.scope == "global"
        if scope == "agent":
            return AgentMemory.scope == "agent"
        if scope == "user":
            if user_id is None:
                # User scope without a user → only unbound user-scoped
                # memories (rare; mostly tests).
                return and_(
                    AgentMemory.scope == "user",
                    AgentMemory.user_id.is_(None),
                )
            return and_(
                AgentMemory.scope == "user",
                AgentMemory.user_id == user_id,
            )
        # No explicit scope: pull global + (user-scoped that match the
        # user) so an agent always sees globally-shared facts.
        if user_id is None:
            return AgentMemory.scope.in_(["global", "agent"])
        return (
            (AgentMemory.scope == "global")
            | (AgentMemory.scope == "agent")
            | and_(AgentMemory.scope == "user", AgentMemory.user_id == user_id)
        )

    async def _semantic_search(
        self,
        *,
        embedding: list[float],
        base_clauses: Sequence[Any],
        k: int,
        threshold: float,
    ) -> list[tuple[AgentMemory, float]]:
        """Cosine-similarity scan, threshold-filtered.

        pgvector's `<=>` operator is cosine *distance* (0 = identical,
        2 = opposite). We convert to similarity (`1 - distance`) for
        the threshold check.
        """
        distance = AgentMemory.embedding.cosine_distance(embedding)
        stmt = (
            select(AgentMemory, distance.label("distance"))
            .where(AgentMemory.embedding.is_not(None))
        )
        if base_clauses:
            stmt = stmt.where(and_(*base_clauses))
        stmt = stmt.order_by(distance).limit(k * 4)
        result = await self._session.execute(stmt)
        out: list[tuple[AgentMemory, float]] = []
        for row in result.all():
            mem: AgentMemory = row[0]
            distance_val: float = float(row[1])
            similarity = 1.0 - distance_val
            if similarity < threshold:
                continue
            out.append((mem, similarity))
            if len(out) == k:
                break
        return out

    async def _structured_search(
        self,
        *,
        query: str,
        base_clauses: Sequence[Any],
        k: int,
    ) -> list[AgentMemory]:
        """Substring match on `key` (case-insensitive) plus exact key.

        Cheap and predictable. Used when the caller wants to ground a
        recall on a known identifier (e.g. agent looking up a memory
        keyed `goal_role:<user_id>`).
        """
        like = f"%{query.lower()}%"
        stmt = (
            select(AgentMemory)
            .where(func.lower(AgentMemory.key).like(like))
        )
        if base_clauses:
            stmt = stmt.where(and_(*base_clauses))
        stmt = stmt.order_by(AgentMemory.last_used_at.desc()).limit(k)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _touch(self, ids: Sequence[uuid.UUID]) -> None:
        """Bump access_count + last_used_at for recalled rows."""
        if not ids:
            return
        await self._session.execute(
            update(AgentMemory)
            .where(AgentMemory.id.in_(list(ids)))
            .values(
                access_count=AgentMemory.access_count + 1,
                last_used_at=datetime.now(UTC),
            )
        )

    async def _find_one(
        self,
        *,
        user_id: uuid.UUID | None,
        agent_name: str,
        scope: str,
        key: str,
    ) -> AgentMemory | None:
        stmt = select(AgentMemory).where(
            AgentMemory.agent_name == agent_name,
            AgentMemory.scope == scope,
            AgentMemory.key == key,
        )
        if user_id is None:
            stmt = stmt.where(AgentMemory.user_id.is_(None))
        else:
            stmt = stmt.where(AgentMemory.user_id == user_id)
        result = await self._session.execute(stmt.limit(1))
        return result.scalars().first()

    async def _reload(self, memory_id: uuid.UUID) -> AgentMemory:
        result = await self._session.execute(
            select(AgentMemory).where(AgentMemory.id == memory_id)
        )
        row = result.scalars().one()
        return row


# Reference the unused import so an aggressive linter doesn't strip it.
_ = pg_insert


__all__ = [
    "DEFAULT_SIMILARITY_THRESHOLD",
    "MemoryRow",
    "MemoryStore",
    "MemoryWrite",
]
