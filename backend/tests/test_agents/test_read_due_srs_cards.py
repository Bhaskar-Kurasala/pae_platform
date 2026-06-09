"""D12 CP3 Phase 1 — pin read_due_srs_cards against real srs_cards schema.

Bug 7: original query referenced three columns that don't exist on
srs_cards:
  - `concept` → real column is `concept_key`
  - `next_review_at` (5 occurrences) → real column is `next_due_at`
  - `student_id` → real column is `user_id`

Load-bearing assertion: SQL executes against real srs_cards schema.
A regression to any of the three wrong column names fails at parse time.

Postgres-backed; skipped when no Postgres reachable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.agents.primitives.communication import _active_session  # type: ignore[attr-defined]

pytestmark = [pytest.mark.asyncio]

DEFAULT_TEST_DSN = "postgresql+asyncpg://postgres:postgres@localhost:5433/platform"


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
    if not _pg_available:
        pytest.skip("Postgres at TEST_PG_DSN not reachable.")

    schema_name = f"rdsc_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(
        _dsn(),
        future=True,
        connect_args={
            "server_settings": {"search_path": f"{schema_name},public"},
        },
    )

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'SET search_path TO "{schema_name}", public')
        # Schema mirrors production srs_cards (the columns the query reads).
        await conn.exec_driver_sql(
            """
            CREATE TABLE srs_cards (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                concept_key VARCHAR(128) NOT NULL,
                ease_factor DOUBLE PRECISION NOT NULL DEFAULT 2.5,
                next_due_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
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


async def _call_tool(
    session: AsyncSession, student_id: uuid.UUID, days_ahead: int = 7
) -> Any:
    from app.agents.tools.agent_specific.study_planner.read_due_srs_cards import (
        ReadDueSrsCardsInput,
        read_due_srs_cards,
    )

    token = _active_session.set(session)
    try:
        return await read_due_srs_cards(
            ReadDueSrsCardsInput(student_id=student_id, days_ahead=days_ahead)
        )
    finally:
        _active_session.reset(token)


async def test_query_executes_against_real_schema_no_data(
    pg_session: AsyncSession,
) -> None:
    """SQL parses against the real srs_cards schema with no rows.

    Load-bearing: regression to `concept`, `next_review_at`, or
    `student_id` fails at parse time with UndefinedColumnError.
    """
    uid = uuid.uuid4()
    result = await _call_tool(pg_session, uid)

    assert result.cards_due == []
    assert result.total_due == 0
    assert result.overdue_count == 0


async def test_returns_due_card(pg_session: AsyncSession) -> None:
    """A card with next_due_at within the days_ahead window is returned."""
    uid = uuid.uuid4()
    soon = datetime.now(UTC) + timedelta(days=2)

    await pg_session.execute(
        sql_text(
            "INSERT INTO srs_cards (user_id, concept_key, next_due_at) "
            "VALUES (:uid, :ck, :due)"
        ),
        {"uid": uid, "ck": "rag.indexing", "due": soon},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid, days_ahead=7)
    assert result.total_due == 1
    assert result.cards_due[0].concept == "rag.indexing"
    assert result.overdue_count == 0


async def test_overdue_card_flagged(pg_session: AsyncSession) -> None:
    """A card with next_due_at in the past flags is_overdue."""
    uid = uuid.uuid4()
    past = datetime.now(UTC) - timedelta(days=1)

    await pg_session.execute(
        sql_text(
            "INSERT INTO srs_cards (user_id, concept_key, next_due_at) "
            "VALUES (:uid, :ck, :due)"
        ),
        {"uid": uid, "ck": "vector.embeddings", "due": past},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid)
    assert result.total_due == 1
    assert result.overdue_count == 1


async def test_card_outside_window_not_returned(
    pg_session: AsyncSession,
) -> None:
    """A card due 30 days out is NOT returned with a 7-day window."""
    uid = uuid.uuid4()
    far = datetime.now(UTC) + timedelta(days=30)

    await pg_session.execute(
        sql_text(
            "INSERT INTO srs_cards (user_id, concept_key, next_due_at) "
            "VALUES (:uid, :ck, :due)"
        ),
        {"uid": uid, "ck": "future.topic", "due": far},
    )
    await pg_session.flush()

    result = await _call_tool(pg_session, uid, days_ahead=7)
    assert result.total_due == 0
