"""Per-tool test fixtures for billing_support's four lookup tools.

Uses the same throwaway-schema pattern as
tests/test_agents/primitives/conftest.py — each test gets its own
Postgres schema with just the tables the billing tools touch
(orders, refunds, payment_attempts, course_entitlements, courses,
users, student_inbox). FK constraints are dropped from the test
versions of the tables to keep seeding simple; the tools' SQL
doesn't depend on FK enforcement at query time.

Skips the test when no Postgres is reachable so the suite still
runs in pure-SQLite environments.
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
    """Per-test session bound to a throwaway Postgres schema with
    the billing-tool tables. FKs dropped to keep seeding simple."""
    if not _pg_available:
        pytest.skip(
            "Postgres at TEST_PG_DSN is not reachable; "
            "billing-tool tests need real asyncpg behavior."
        )

    schema_name = f"billing_test_{uuid.uuid4().hex[:8]}"
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

        # users (parent table for FKs in real schema; standalone here)
        await conn.exec_driver_sql(
            """
            CREATE TABLE users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(320) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NULL,
                full_name VARCHAR(200) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # courses (joined by lookup_active_entitlements)
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

        # orders — mirror app/models/order.py exactly
        await conn.exec_driver_sql(
            """
            CREATE TABLE orders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                target_type VARCHAR(20) NOT NULL,
                target_id UUID NOT NULL,
                amount_cents INT NOT NULL,
                currency VARCHAR(8) NOT NULL DEFAULT 'INR',
                provider VARCHAR(20) NOT NULL,
                provider_order_id VARCHAR(255) NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'created',
                failure_reason TEXT NULL,
                receipt_number VARCHAR(40) NULL UNIQUE,
                gst_breakdown JSON NULL,
                metadata JSON NOT NULL DEFAULT '{}'::json,
                paid_at TIMESTAMPTZ NULL,
                fulfilled_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # payment_attempts
        await conn.exec_driver_sql(
            """
            CREATE TABLE payment_attempts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                order_id UUID NOT NULL,
                provider VARCHAR(20) NOT NULL,
                provider_payment_id VARCHAR(255) NULL,
                provider_signature VARCHAR(512) NULL,
                amount_cents INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'created',
                failure_reason TEXT NULL,
                raw_response JSON NULL,
                attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # refunds
        await conn.exec_driver_sql(
            """
            CREATE TABLE refunds (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                order_id UUID NOT NULL,
                payment_attempt_id UUID NULL,
                provider VARCHAR(20) NOT NULL,
                provider_refund_id VARCHAR(255) NULL,
                amount_cents INT NOT NULL,
                currency VARCHAR(8) NOT NULL DEFAULT 'INR',
                reason TEXT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                raw_response JSON NULL,
                processed_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # course_entitlements
        await conn.exec_driver_sql(
            """
            CREATE TABLE course_entitlements (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                course_id UUID NOT NULL,
                source VARCHAR(20) NOT NULL,
                source_ref UUID NULL,
                granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                revoked_at TIMESTAMPTZ NULL,
                expires_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # student_inbox (escalate_to_human writes here)
        await conn.exec_driver_sql(
            """
            CREATE TABLE student_inbox (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                agent_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                cta_label TEXT NULL,
                cta_url TEXT NULL,
                read_at TIMESTAMPTZ NULL,
                dismissed_at TIMESTAMPTZ NULL,
                expires_at TIMESTAMPTZ NULL,
                metadata JSONB NOT NULL DEFAULT '{}',
                idempotency_key TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # The partial unique index that escalate_to_human's
        # idempotency-check relies on
        await conn.exec_driver_sql(
            """
            CREATE UNIQUE INDEX student_inbox_user_idem_uidx
            ON student_inbox (user_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
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
    """Set _active_session contextvar so tool bodies can recover the
    session via get_active_session(). Same pattern as universal-tool
    test conftest. Reset on teardown."""
    token = comm_mod._active_session.set(pg_session)
    try:
        yield pg_session
    finally:
        comm_mod._active_session.reset(token)
