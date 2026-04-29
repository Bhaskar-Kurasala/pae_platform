from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


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
