from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Any

import structlog
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.engine.interfaces import ExecutionContext
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = structlog.get_logger()


class Base(DeclarativeBase):
    pass


# PR2/B5.2 — Postgres `statement_timeout`. Caps any single SQL statement
# at 5 seconds wall-clock. A runaway query can no longer pin a worker
# indefinitely; the request fails fast with a SQLAlchemy
# `OperationalError: canceling statement due to statement timeout`,
# which our global exception handler (PR2/B4.1) wraps in the stable
# error envelope.
#
# 5s is generous for our app shape — the slowest aggregator (Today)
# completes in <300ms p95 against the demo dataset. Anything taking 5s
# is an indexing bug or a runaway scan.
#
# Passed via asyncpg's `server_settings` connect arg, which executes
# `SET statement_timeout = '5s'` on every new connection.
_DB_STATEMENT_TIMEOUT_MS = 5000

# PR3/C8.1 — Slow-query threshold. Anything that takes longer than this
# emits a `slow_query` structlog warning with the SQL, parameters
# (truncated), and duration. 500ms is loud-enough to fire on real
# regressions but quiet-enough not to spam under normal load — most
# aggregator queries finish in <100ms. Tunable via env if it turns out
# to need adjusting; for now a constant is simpler.
SLOW_QUERY_THRESHOLD_MS = 500
_SQL_PREVIEW_MAX_CHARS = 500
_PARAMS_PREVIEW_MAX_CHARS = 200

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    connect_args={
        "server_settings": {
            "statement_timeout": str(_DB_STATEMENT_TIMEOUT_MS),
        },
    },
)


def _truncate(text: str, max_chars: int) -> str:
    """Truncate with a sentinel suffix so log readers can spot truncation."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"…[+{len(text) - max_chars} chars]"


def _attach_slow_query_logger(sync_engine: Any) -> None:
    """Wire `before/after_cursor_execute` events to log slow queries.

    SQLAlchemy emits these events on the *sync* engine even when the
    outer engine is async — `AsyncEngine.sync_engine` is the listener
    target. We stash a perf_counter timestamp in `context._query_start`
    on `before_cursor_execute` and emit the structlog warning on
    `after_cursor_execute` if the elapsed time crossed the threshold.

    Logs SQL + parameters (both truncated) so the on-call can copy-paste
    into psql to reproduce. We intentionally do NOT log result rows — a
    1MB result set in a log line is pure noise.
    """

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        # Stash on `context` so it survives until after_cursor_execute
        # for the same statement on the same connection.
        context._query_start_perf = perf_counter()  # type: ignore[attr-defined]

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after_cursor_execute(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        start = getattr(context, "_query_start_perf", None)
        if start is None:
            return  # paranoia: someone set up the engine without our listener
        duration_ms = (perf_counter() - start) * 1000.0
        if duration_ms < SLOW_QUERY_THRESHOLD_MS:
            return
        log.warning(
            "slow_query",
            duration_ms=round(duration_ms, 2),
            threshold_ms=SLOW_QUERY_THRESHOLD_MS,
            sql=_truncate(statement, _SQL_PREVIEW_MAX_CHARS),
            params=_truncate(repr(parameters), _PARAMS_PREVIEW_MAX_CHARS),
            executemany=executemany,
        )


# Wire the slow-query logger to the *sync* facet of the async engine —
# SQLAlchemy 2.0 dispatches cursor events on the sync engine for both
# sync and async usage. Idempotent: SQLAlchemy dedupes identical
# listeners, but importing this module once at startup is the contract.
_attach_slow_query_logger(engine.sync_engine)


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Re-exported so tests / callers can read the threshold without importing
# the private constant. Type kept as `int` for clarity.
__all__ = [
    "AsyncSessionLocal",
    "Base",
    "SLOW_QUERY_THRESHOLD_MS",
    "engine",
    "get_db",
]
