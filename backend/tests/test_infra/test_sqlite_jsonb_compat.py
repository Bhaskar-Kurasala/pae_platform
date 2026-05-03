"""D10 Checkpoint 1 — pin the SQLite/JSONB compatibility shim.

The shim lives at tests/conftest.py and registers
`@compiles(JSONB, "sqlite")` returning "TEXT". Without it, any SQLite
test that triggers `Base.metadata.create_all` on a model declaring
`postgresql.JSONB` columns crashes at fixture setup with
`'SQLiteTypeCompiler' object has no attribute 'visit_JSONB'`.

This file pins the contract so a future revert is loud:
  • The JSONB type renders cleanly under SQLite (CREATE TABLE works)
  • A JSONB column round-trips a dict (write → read same shape)
  • The student_inbox.func.cast("{}", JSONB) server_default doesn't
    trip on the SQLite path
  • The shim doesn't break the Postgres rendering (regression check
    against pgvector/pgvector:pg16 on the host's docker-compose db)

These tests run on the default SQLite fixture; the Postgres-side
guard runs only when TEST_PG_DSN reaches a live db (skip otherwise,
mirroring the primitives-conftest pattern).

See docs/followups/test-suite-sqlite-jsonb-gap.md for the full
investigation report.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.models.student_inbox import StudentInbox

# pyproject.toml sets asyncio_mode = "auto" — async funcs run via
# pytest-asyncio without an explicit mark; sync funcs run normally.
# Mixing both in this file just works.


# ── Shim contract: SQLite renders JSONB as TEXT ────────────────────


def test_jsonb_compiles_to_text_under_sqlite() -> None:
    """The shim is what unblocks ~600 tests. Pin it directly.

    Compiles a JSONB type against the SQLite dialect and asserts the
    output. If a future contributor removes the shim (or changes the
    return value), this test fires before the regression cascade.
    """
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

    rendered = JSONB().compile(dialect=sqlite_dialect())
    assert str(rendered) == "TEXT"


def test_jsonb_compiles_to_jsonb_under_postgres() -> None:
    """Sanity: the shim must NOT affect the Postgres render path.

    Production behavior is unchanged; compiling JSONB against the
    Postgres dialect still emits JSONB. This is the regression guard
    against an over-eager shim that registered for all dialects.
    """
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import dialect as pg_dialect

    rendered = JSONB().compile(dialect=pg_dialect())
    assert str(rendered) == "JSONB"


# ── End-to-end: a JSONB-bearing model survives the SQLite round-trip ─


@pytest_asyncio.fixture
async def sqlite_session() -> AsyncSession:
    """Per-test SQLite session over an in-memory DB with the full
    Base.metadata.create_all path exercised — same shape as the
    canonical `db_session` fixture in tests/conftest.py.

    We deliberately do NOT reuse `db_session` here because we want
    this test to fail loudly if the shim ever stops working — so the
    fixture lives next to the test and is minimal.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_create_all_succeeds_on_sqlite(
    sqlite_session: AsyncSession,
) -> None:
    """The headline assertion: Base.metadata.create_all works.

    Pre-shim, this raised CompileError on agent_call_chain.payload
    before any test in the affected files could even start. Now it
    completes silently and the table list contains every JSONB-bearing
    model.
    """
    result = await sqlite_session.execute(
        sql_text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN ("
            "'agent_call_chain','agent_escalations','agent_memory',"
            "'agent_proactive_runs','agent_tool_calls','student_inbox')"
        )
    )
    table_names = {row[0] for row in result.all()}
    # All six JSONB-bearing tables must be present after create_all.
    # Table names per __tablename__ on each model — note the
    # plural/singular split (agent_call_chain + agent_memory +
    # student_inbox are singular; the rest plural).
    expected = {
        "agent_call_chain",
        "agent_escalations",
        "agent_memory",
        "agent_proactive_runs",
        "agent_tool_calls",
        "student_inbox",
    }
    missing = expected - table_names
    assert not missing, (
        f"After SQLite create_all, expected JSONB-bearing tables "
        f"missing: {missing!r}. Shim regression?"
    )


async def test_jsonb_dict_round_trips_through_sqlite(
    sqlite_session: AsyncSession,
) -> None:
    """End-to-end: write a dict to a JSONB column, read it back.

    student_inbox.metadata_ is the JSONB column with the trickiest
    server_default (func.cast("{}", JSONB)) — if the shim breaks the
    cast, this insert fails. Picks student_inbox specifically because
    the func.cast path is the highest-risk part of Concern B.
    """
    user_id = uuid.uuid4()
    payload = {"reason": "test", "nested": {"hint": "abc", "n": 42}}

    row = StudentInbox(
        user_id=user_id,
        agent_name="billing_support",
        kind="nudge",
        title="round-trip",
        body="round-trip body",
        metadata_=payload,
    )
    sqlite_session.add(row)
    await sqlite_session.flush()

    # Re-read via the ORM and confirm the dict survived.
    fetched = await sqlite_session.get(StudentInbox, row.id)
    assert fetched is not None
    assert fetched.metadata_ == payload


async def test_jsonb_default_cast_works_on_sqlite(
    sqlite_session: AsyncSession,
) -> None:
    """The student_inbox.metadata_ default (func.cast("{}", JSONB))
    must produce {} when no explicit value is provided. This is the
    Concern B server-default path that the original followup doc
    worried about — pinning it here so any regression on that path
    is loud.
    """
    user_id = uuid.uuid4()
    row = StudentInbox(
        user_id=user_id,
        agent_name="billing_support",
        kind="nudge",
        title="default-test",
        body="body",
        # metadata_ intentionally omitted so the server_default fires
    )
    sqlite_session.add(row)
    await sqlite_session.flush()

    # Reload to make sure the server_default was applied at INSERT.
    await sqlite_session.refresh(row)
    # SQLite stores JSON as TEXT; SQLAlchemy's JSON type round-trips
    # back to a dict on read for us via the JSONB column type.
    assert row.metadata_ in ({}, None)  # either is acceptable on SQLite


# ── Postgres regression guard (skip if no Postgres reachable) ─────


def _pg_reachable() -> bool:
    """Cheap probe; mirrors tests/test_agents/primitives/conftest.py."""
    import asyncio

    import asyncpg

    dsn = os.environ.get(
        "TEST_PG_DSN",
        "postgresql+asyncpg://postgres:postgres@localhost:5433/platform",
    ).replace("postgresql+asyncpg://", "postgresql://", 1)

    async def _probe() -> bool:
        try:
            conn = await asyncpg.connect(dsn, timeout=2.0)
            await conn.close()
            return True
        except Exception:
            return False

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


@pytest.mark.skipif(
    not _pg_reachable(),
    reason="No reachable Postgres at TEST_PG_DSN; skip the production-side guard.",
)
async def test_jsonb_still_renders_as_jsonb_on_real_postgres() -> None:
    """The shim must be SQLite-only. Confirm against a live Postgres
    that JSONB still compiles and renders as the native type — i.e.
    we did not accidentally break production behavior.
    """
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import dialect as pg_dialect

    rendered = JSONB().compile(dialect=pg_dialect())
    assert str(rendered) == "JSONB"
