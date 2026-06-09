"""Per-tool test fixtures for senior_engineer's two memory-read tools.

Senior_engineer's tools wrap MemoryStore.recall over agent_memory
rows, so fixtures only need agent_memory + the agent_memory_scope
enum + pgvector. Mirrors tests/test_agents/primitives/conftest.py
which exercises MemoryStore directly — the only difference is the
session is bound to the tool's _active_session contextvar so the
@tool body can pick it up.

Skips when no Postgres is reachable so the suite still runs in
pure-SQLite environments.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.agents.primitives import communication as comm_mod

DEFAULT_TEST_DSN = (
    "postgresql+asyncpg://postgres:postgres@localhost:5433/platform"
)


def _dsn() -> str:
    return os.environ.get("TEST_PG_DSN", DEFAULT_TEST_DSN)


async def _postgres_reachable(dsn: str) -> bool:
    raw = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        conn = await asyncpg.connect(raw, timeout=2.0)
        await conn.close()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="module")
async def _pg_available() -> bool:
    return await _postgres_reachable(_dsn())


@pytest_asyncio.fixture
async def pg_session(_pg_available: bool) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session bound to a throwaway Postgres schema with
    just agent_memory + the scope enum + pgvector."""
    if not _pg_available:
        pytest.skip(
            "Postgres at TEST_PG_DSN is not reachable; senior_engineer "
            "tool tests require pgvector and asyncpg."
        )

    schema_name = f"se_tools_{uuid.uuid4().hex[:8]}"
    base_dsn = _dsn()
    engine = create_async_engine(
        base_dsn,
        future=True,
        connect_args={
            "server_settings": {"search_path": f"{schema_name},public"},
        },
    )

    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')

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

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'DROP SCHEMA "{schema_name}" CASCADE')
    await engine.dispose()


@contextmanager
def active_session(session: AsyncSession) -> Any:
    """Bind the tool's _active_session contextvar to ``session`` for the
    duration of the with-block. Tools called inside read this via
    ``get_active_session``; outside production this is the only way
    to drive a tool body directly."""
    token = comm_mod._active_session.set(session)
    try:
        yield
    finally:
        comm_mod._active_session.reset(token)
