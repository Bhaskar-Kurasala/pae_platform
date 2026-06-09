"""Per-tool fixtures for project_evaluator's read tools (D17b/ITEM 2).

Mirrors the billing_support conftest's throwaway-schema pattern:
each test gets a Postgres schema with users + exercises + lessons +
courses + exercise_submissions + course_entitlements (the entitlement
chain ITEM 2.B's read_rubric_for_capstone gates against).

FK constraints intentionally omitted on the test schemas — the tools'
SQL doesn't depend on FK enforcement at query time, and skipping FKs
keeps seed helpers simple. Skips when no Postgres is reachable so the
test suite still works in pure-SQLite environments.
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
    if not _pg_available:
        pytest.skip(
            "Postgres at TEST_PG_DSN is not reachable; project_evaluator "
            "tool tests need real asyncpg behavior."
        )

    schema_name = f"pe_test_{uuid.uuid4().hex[:8]}"
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
        await conn.exec_driver_sql(f'SET search_path TO "{schema_name}", public')

        await conn.exec_driver_sql(
            """
            CREATE TABLE users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(320) NOT NULL UNIQUE,
                full_name VARCHAR(200) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        await conn.exec_driver_sql(
            """
            CREATE TABLE courses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                slug VARCHAR(120) NOT NULL,
                title VARCHAR(255) NOT NULL,
                price_cents INT NOT NULL DEFAULT 0,
                is_published BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        await conn.exec_driver_sql(
            """
            CREATE TABLE lessons (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                course_id UUID NOT NULL,
                title VARCHAR(255) NOT NULL,
                position INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        await conn.exec_driver_sql(
            """
            CREATE TABLE exercises (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                lesson_id UUID NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NULL,
                rubric JSONB NULL,
                is_capstone BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        await conn.exec_driver_sql(
            """
            CREATE TABLE exercise_submissions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id UUID NOT NULL,
                exercise_id UUID NOT NULL,
                code TEXT NULL,
                github_pr_url TEXT NULL,
                self_explanation TEXT NULL,
                feedback TEXT NULL,
                ai_feedback JSONB NULL,
                score INT NULL,
                status VARCHAR(40) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        await conn.exec_driver_sql(
            """
            CREATE TABLE course_entitlements (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                course_id UUID NOT NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'purchase',
                granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                revoked_at TIMESTAMPTZ NULL,
                expires_at TIMESTAMPTZ NULL,
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


@pytest_asyncio.fixture
async def session_on_contextvar(pg_session: AsyncSession):
    token = comm_mod._active_session.set(pg_session)
    try:
        yield pg_session
    finally:
        comm_mod._active_session.reset(token)
