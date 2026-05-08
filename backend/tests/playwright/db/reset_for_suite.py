"""D18 Phase A CP2 — reset playwright_test from the template.

Per-suite reset entry point: drops `playwright_test` (if it exists)
and re-creates it from `playwright_test_template` via Postgres'
TEMPLATE clause. This is the fast path (~1-2s for the full schema +
seed) that lets pytest-playwright start each suite from a clean
known state without paying the migration cost.

Usage:
  # Programmatic (called by conftest's session-scoped fixture):
  from backend.tests.playwright.db.reset_for_suite import reset_database_from_template
  await reset_database_from_template()

  # Or from a shell:
  python backend/tests/playwright/db/reset_for_suite.py

Pre-condition: `playwright_test_template` must exist (created by
`create_template.py`). If absent, this script surfaces a clear error
rather than silently re-running migrations.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import asyncpg

TEMPLATE_DB_NAME = "playwright_test_template"
TEST_DB_NAME = "playwright_test"
DEFAULT_ADMIN_DSN = "postgresql://postgres:postgres@db:5432/postgres"


def _admin_dsn() -> str:
    return os.environ.get("PLAYWRIGHT_ADMIN_DSN", DEFAULT_ADMIN_DSN)


def _test_dsn() -> str:
    """Return the asyncpg-shape DSN for the test database itself.

    Used by tests + the backend's app code (which converts to
    postgresql+asyncpg:// shape via SQLAlchemy)."""
    base = _admin_dsn()
    if base.endswith("/postgres"):
        return base[: -len("postgres")] + TEST_DB_NAME
    raise ValueError(
        f"PLAYWRIGHT_ADMIN_DSN must end in /postgres; got {base!r}"
    )


async def _terminate_existing_connections(
    conn: asyncpg.Connection, db_name: str
) -> None:
    """Force-disconnect any open connections to db_name before DROP.

    Postgres refuses to drop a database with active connections.
    Tests that crash mid-suite can leave connections hanging; this
    cleans them up so the reset is idempotent against ungraceful
    prior runs.
    """
    await conn.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = $1
          AND pid <> pg_backend_pid()
        """,
        db_name,
    )


async def _verify_template_exists(conn: asyncpg.Connection) -> None:
    exists = await conn.fetchval(
        "SELECT 1 FROM pg_database WHERE datname = $1", TEMPLATE_DB_NAME
    )
    if not exists:
        raise RuntimeError(
            f"Template database {TEMPLATE_DB_NAME!r} does not exist. "
            f"Run create_template.py first to seed the template."
        )


async def reset_database_from_template() -> float:
    """Reset playwright_test from the template; return elapsed seconds.

    Programmatic entry point invoked by conftest at session scope.
    Returns elapsed wall-time so the caller (or test report) can
    surface the cost.
    """
    started = time.monotonic()
    admin_conn = await asyncpg.connect(_admin_dsn())
    try:
        await _verify_template_exists(admin_conn)
        await _terminate_existing_connections(admin_conn, TEST_DB_NAME)
        await admin_conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")
        await admin_conn.execute(
            f"CREATE DATABASE {TEST_DB_NAME} TEMPLATE {TEMPLATE_DB_NAME}"
        )
    finally:
        await admin_conn.close()
    return time.monotonic() - started


async def main() -> int:
    elapsed = await reset_database_from_template()
    print(
        f"[reset_for_suite] {TEST_DB_NAME} reset from "
        f"{TEMPLATE_DB_NAME} in {elapsed:.2f}s",
        file=sys.stderr,
    )
    if elapsed > 5.0:
        print(
            f"[reset_for_suite] WARN: reset took {elapsed:.2f}s "
            "(STOP threshold per CP2 spec is 5s; investigate)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
