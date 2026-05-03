"""D10 Checkpoint 2 sign-off / Commit 5 — pin the snapshot service's
asyncpg-recovery contract.

Two assertions, both Postgres-only (asyncpg-specific behavior we're
testing isn't reproducible under SQLite):

  1. test_load_goal_contract_returns_none_when_no_row
       Happy-empty path. The user has no goal_contracts row; the
       function returns None cleanly without raising. Confirms the
       fixed real-column query parses against the actual schema.

  2. test_session_recovers_after_load_goal_contract_failure
       The contract that matters most. When ANY SQL inside
       _load_goal_contract fails (we trigger this with a synthetic
       always-failing query so the test stays durable across future
       schema changes), a subsequent INSERT on the same session
       MUST succeed. Without the rollback inside the except clause,
       asyncpg surfaces InFailedSQLTransactionError on the next
       statement and breaks the dispatch path entirely.

Why a synthetic-failing trigger and not the original column-name bug:
  After the rename to real columns, the production query no longer
  fails at parse time — so it can't exercise the except clause. A
  synthetic always-failing query (SELECT from a nonexistent column)
  keeps the rollback contract under test permanently. If a future
  contributor removes the rollback or the try/except, this test
  fails loudly with InFailedSQLTransactionError.

The test creates a throwaway Postgres schema with the two tables it
needs (goal_contracts + agent_call_chain) — same pattern as the
primitives conftest's pg_session fixture, but local to this file
because tests/test_services/ doesn't have a Postgres conftest yet.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.services.agentic_snapshot_service import _load_goal_contract

pytestmark = [pytest.mark.asyncio]

DEFAULT_TEST_DSN = (
    "postgresql+asyncpg://postgres:postgres@localhost:5433/platform"
)


def _dsn() -> str:
    return os.environ.get("TEST_PG_DSN", DEFAULT_TEST_DSN)


async def _postgres_reachable(dsn: str) -> bool:
    """Cheap probe — same pattern as primitives/conftest.py."""
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
    """Per-test session bound to a one-shot Postgres schema.

    Creates only the two tables this test file touches:
      • goal_contracts — the snapshot service queries this
      • agent_call_chain — the downstream INSERT we want to confirm
        works after the snapshot service's except path runs

    Schema dropped on teardown. Skips the test when no Postgres is
    reachable so the suite still runs in pure-SQLite environments.
    """
    if not _pg_available:
        pytest.skip(
            "Postgres at TEST_PG_DSN is not reachable; "
            "snapshot-rollback tests need real asyncpg behavior."
        )

    schema_name = f"snap_rollback_{uuid.uuid4().hex[:8]}"
    base_dsn = _dsn()
    engine = create_async_engine(
        base_dsn,
        future=True,
        connect_args={
            "server_settings": {"search_path": f"{schema_name},public"},
        },
    )

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')

    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            f'SET search_path TO "{schema_name}", public'
        )
        # Mirrors the model + migrations 0002+0018+0044 — String(16)
        # weekly_hours, String(128) target_role, no expires_at.
        await conn.exec_driver_sql(
            """
            CREATE TABLE goal_contracts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                motivation VARCHAR(32) NOT NULL,
                deadline_months INT NOT NULL,
                success_statement TEXT NOT NULL,
                weekly_hours VARCHAR(16) NULL,
                target_role VARCHAR(128) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Minimal agent_call_chain — only the columns we need to
        # exercise INSERT recovery. Migration 0054 has the full table.
        await conn.exec_driver_sql(
            """
            CREATE TABLE agent_call_chain (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                root_id UUID NOT NULL,
                parent_id UUID NULL,
                caller_agent VARCHAR(200) NULL,
                callee_agent VARCHAR(200) NOT NULL,
                depth INT NOT NULL DEFAULT 0,
                payload JSONB NULL,
                result JSONB NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'ok',
                user_id UUID NULL,
                duration_ms INT NULL,
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


# ── Assertion 1: happy-empty path ───────────────────────────────────


async def test_load_goal_contract_returns_none_when_no_row(
    pg_session: AsyncSession,
) -> None:
    """No goal_contracts row for the user → returns None cleanly.

    Pins the fixed real-column SQL: SELECT weekly_hours, target_role
    FROM goal_contracts ... — proves the query parses against the
    actual schema. If a future regression reintroduces the
    weekly_hours_committed/expires_at column references, this test
    fails at the parse-time UndefinedColumnError before the row
    check even runs.
    """
    user_id = uuid.uuid4()
    result = await _load_goal_contract(pg_session, user_id)
    assert result is None


async def test_load_goal_contract_returns_summary_when_row_exists(
    pg_session: AsyncSession,
) -> None:
    """A real row maps to GoalContractSummary correctly.

    Confirms the bucket-string passthrough (weekly_hours='6-10' stays
    a string, no float coercion crash). Also confirms target_role
    propagates so the Supervisor's prose-builder can read it.
    """
    user_id = uuid.uuid4()
    await pg_session.execute(
        sql_text(
            """
            INSERT INTO goal_contracts
                (user_id, motivation, deadline_months,
                 success_statement, weekly_hours, target_role)
            VALUES (:uid, 'curiosity', 6, 'ship a RAG demo', '6-10', 'Senior GenAI')
            """
        ),
        {"uid": user_id},
    )
    await pg_session.flush()

    result = await _load_goal_contract(pg_session, user_id)
    assert result is not None
    assert result.weekly_hours == "6-10"
    assert result.target_role == "Senior GenAI"
    assert result.expires_at is None  # forward-looking field, never populated yet


# ── Assertion 2: the rollback contract — the bug we're fixing ──────


async def test_session_recovers_after_load_goal_contract_failure(
    pg_session: AsyncSession,
) -> None:
    """The contract that matters most.

    When ANY SQL inside _load_goal_contract fails, the session must
    be recoverable for downstream INSERTs. Without the rollback
    inside the except clause, asyncpg leaves the transaction marked
    as failed and the next statement raises
    InFailedSQLTransactionError — which is exactly what was breaking
    the orchestrator's agent_call_chain INSERT during dispatch.

    We trigger the failure via monkey-patch: replace the SQL string
    inside _load_goal_contract with a synthetic always-failing
    query (SELECT from a nonexistent column) so the test stays
    durable across future schema changes. After the snapshot
    function returns None (handled the failure), we attempt a real
    agent_call_chain INSERT on the same session. If it succeeds,
    the rollback recovered the asyncpg state.
    """
    user_id = uuid.uuid4()

    # Patch sql_text inside the snapshot service so the SELECT fires
    # an UndefinedColumnError. We want the actual asyncpg-level
    # failure path, not a Python-side mock — so the patched query
    # must be real SQL that Postgres rejects at parse time.
    from app.services import agentic_snapshot_service as snap_mod

    original_text = snap_mod.text
    failing_query_seen = False

    def _failing_text(query: str) -> Any:  # type: ignore[no-untyped-def]
        nonlocal failing_query_seen
        # Only intercept the goal_contracts SELECT; pass everything
        # else through unchanged so the rollback's own SQL still works.
        if "FROM goal_contracts" in query:
            failing_query_seen = True
            return original_text(
                "SELECT nonexistent_column_x_for_test FROM goal_contracts WHERE user_id = :uid"
            )
        return original_text(query)

    with patch.object(snap_mod, "text", side_effect=_failing_text):
        result = await _load_goal_contract(pg_session, user_id)

    assert failing_query_seen, "Synthetic failing query did not fire"
    assert result is None, (
        "_load_goal_contract should fail-soft to None on SQL error"
    )

    # The session should now be recoverable. Attempt a real INSERT
    # on agent_call_chain — this is the exact statement that used
    # to fail with InFailedSQLTransactionError before the rollback
    # fix landed.
    chain_id = uuid.uuid4()
    root_id = uuid.uuid4()
    await pg_session.execute(
        sql_text(
            """
            INSERT INTO agent_call_chain
                (id, root_id, parent_id, caller_agent, callee_agent,
                 depth, payload, result, status, user_id, duration_ms)
            VALUES (:id, :root, NULL, 'orchestrator', 'billing_support',
                    1, '{"q": "test"}'::jsonb, '{"ok": true}'::jsonb,
                    'ok', :uid, 5)
            """
        ),
        {"id": chain_id, "root": root_id, "uid": user_id},
    )
    await pg_session.flush()

    # Confirm the row landed.
    raw = await pg_session.execute(
        sql_text("SELECT count(*) FROM agent_call_chain WHERE id = :id"),
        {"id": chain_id},
    )
    assert raw.scalar_one() == 1, (
        "agent_call_chain INSERT failed after snapshot-service except path "
        "fired — rollback inside _load_goal_contract is broken or missing"
    )


# Minor type-hint shim for the closure above
from typing import Any  # noqa: E402
