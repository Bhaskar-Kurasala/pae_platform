"""Postgres + pgvector fixtures for the Agentic OS primitives tests.

The repo's default test DB is SQLite in-memory, which can't host
pgvector. The primitives layer is Postgres-specific (vector columns,
HNSW indexes, jsonb), so each primitives test file shares this
conftest's `pg_session` fixture and skips automatically when the
local Postgres isn't reachable.

Why a per-test schema instead of a separate database:
  • Faster: schema creation/teardown is a few hundred ms; spinning a
    new database per session burns whole seconds.
  • Self-contained: nothing leaks into the dev `platform` data even
    if a test crashes mid-run.
  • Same connection pool as the app — catches asyncpg quirks the
    SQLite suite never sees.

Activation:
  • Default DSN points at the docker-compose `db` service via the
    host's mapped port (5433). Override with TEST_PG_DSN env var.
  • If asyncpg can't connect, every test using `pg_session` is
    marked `xfail(strict=False)` so CI without Postgres still runs
    the rest of the suite green.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Default points at the docker-compose dev DB exposed on host:5433.
# Override via TEST_PG_DSN env var (e.g. for CI runners).
DEFAULT_TEST_DSN = (
    "postgresql+asyncpg://postgres:postgres@localhost:5433/platform"
)


def _dsn() -> str:
    return os.environ.get("TEST_PG_DSN", DEFAULT_TEST_DSN)


async def _postgres_reachable(dsn: str) -> bool:
    """Cheap probe — try a single asyncpg connect with a tight timeout.

    Returns True iff we get a working connection. False covers any
    failure (DNS, port, auth, server down). Tests that depend on
    Postgres get skipped on False so the suite runs against pure-
    SQLite environments without manual marker fiddling.
    """
    raw = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        conn = await asyncpg.connect(raw, timeout=2.0)
        await conn.close()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="session")
async def _pg_available() -> bool:
    return await _postgres_reachable(_dsn())


@pytest_asyncio.fixture
async def pg_session(_pg_available: bool) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session bound to a one-shot Postgres schema.

    Each test gets its own schema named `aos_test_<random8>` with
    `agent_memory` (and the `agent_memory_scope` enum) created from
    the live ORM metadata. The schema is dropped at teardown.

    The vector extension is created in `public` if absent — pgvector
    types live in the schema where the extension is installed, but
    they're usable from any schema after that.
    """
    if not _pg_available:
        pytest.skip(
            "Postgres at TEST_PG_DSN is not reachable; primitives tests "
            "require pgvector and asyncpg."
        )

    schema_name = f"aos_test_{uuid.uuid4().hex[:8]}"
    base_dsn = _dsn()
    engine = create_async_engine(
        base_dsn,
        future=True,
        connect_args={
            # Pin search_path so SQLAlchemy's metadata operations land
            # inside our throwaway schema. The vector extension lives
            # in `public` and is reachable through the search_path.
            "server_settings": {"search_path": f"{schema_name},public"},
        },
    )

    # Pre-create the schema and the extension in `public` (idempotent).
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')

    # Create the enum + tables we need INSIDE the schema. We do this by
    # hand (not Base.metadata.create_all) because the migration owns
    # the enum and we want a tight subset for primitives tests.
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            f'SET search_path TO "{schema_name}", public'
        )
        await conn.exec_driver_sql(
            "CREATE TYPE agent_memory_scope AS ENUM ('user','agent','global')"
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE agent_memory (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NULL,
                agent_name TEXT NOT NULL,
                scope agent_memory_scope NOT NULL DEFAULT 'user',
                key TEXT NOT NULL,
                value JSONB NOT NULL,
                embedding vector(1536),
                valence REAL NOT NULL DEFAULT 0.0
                    CHECK (valence BETWEEN -1.0 AND 1.0),
                confidence REAL NOT NULL DEFAULT 1.0
                    CHECK (confidence BETWEEN 0.0 AND 1.0),
                source_message_id UUID NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                access_count INT NOT NULL DEFAULT 0,
                expires_at TIMESTAMPTZ NULL
            )
            """
        )
        await conn.exec_driver_sql(
            "CREATE INDEX agent_memory_user_scope_idx "
            "ON agent_memory (user_id, scope)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX agent_memory_embedding_idx "
            "ON agent_memory USING hnsw (embedding vector_cosine_ops)"
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
            await session.rollback()
        finally:
            pass

    # Drop the schema on teardown.
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'DROP SCHEMA "{schema_name}" CASCADE')
    await engine.dispose()


@pytest.fixture
def voyage_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the embeddings layer to take the hash fallback path.

    Used by tests that want the deterministic 1536-dim shape and
    don't want to burn API credits / require network access.
    """
    monkeypatch.setattr(
        "app.core.config.settings.voyage_api_key", "", raising=False
    )
