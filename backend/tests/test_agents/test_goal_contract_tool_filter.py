"""D12 CP3 Part D.3 — pin expires_at filter in goal_contract reader tools.

Tests cover:
  career_coach/read_goal_contract  — D.1 patch
  study_planner/read_goal_contract — D.2 patch

For each:
  • test_returns_active_contract_null_expires_at  — row with NULL expires_at is returned
  • test_returns_active_contract_future_expires_at — row with future expires_at is returned
  • test_filters_expired_contract               — row with past expires_at is NOT returned

Tests require a real Postgres session (asyncpg) because:
  1. The filter uses `now()` which only works in Postgres.
  2. We want to pin against real SQL semantics, not SQLite approximations.

Tests are automatically skipped when Postgres is unreachable so the
pure-SQLite CI suite still runs green.
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
    """Per-test throwaway Postgres schema with goal_contracts only."""
    if not _pg_available:
        pytest.skip(
            "Postgres at TEST_PG_DSN not reachable; "
            "expires_at filter tests need real asyncpg."
        )

    schema_name = f"gc_tool_filter_{uuid.uuid4().hex[:8]}"
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
        await conn.exec_driver_sql(
            """
            CREATE TABLE goal_contracts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL,
                motivation TEXT NOT NULL DEFAULT '',
                deadline_months INT NOT NULL DEFAULT 6,
                success_statement TEXT NOT NULL DEFAULT '',
                weekly_hours VARCHAR(16) NULL,
                target_role VARCHAR(128) NULL,
                expires_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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


async def _insert_contract(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    weekly_hours: str = "6-10",
    target_role: str = "Senior GenAI",
    expires_at: datetime | None = None,
) -> None:
    await session.execute(
        sql_text(
            """
            INSERT INTO goal_contracts
                (user_id, weekly_hours, target_role, expires_at)
            VALUES (:uid, :wh, :tr, :ea)
            """
        ),
        {
            "uid": user_id,
            "wh": weekly_hours,
            "tr": target_role,
            "ea": expires_at,
        },
    )
    await session.flush()


# ── career_coach / read_goal_contract ─────────────────────────────────

class TestCareerCoachReadGoalContract:
    """Pins the expires_at filter added at D12 CP3 Part D.1."""

    async def _call(self, session: AsyncSession, student_id: uuid.UUID) -> Any:
        from app.agents.tools.agent_specific.career_coach.read_goal_contract import (
            ReadGoalContractInput,
            read_goal_contract,
        )

        token = _active_session.set(session)
        try:
            return await read_goal_contract(ReadGoalContractInput(student_id=student_id))
        finally:
            _active_session.reset(token)

    async def test_returns_active_contract_null_expires_at(
        self, pg_session: AsyncSession
    ) -> None:
        """Row with NULL expires_at (permanent contract) is returned."""
        uid = uuid.uuid4()
        await _insert_contract(pg_session, uid, expires_at=None)

        result = await self._call(pg_session, uid)

        assert result.has_contract is True
        assert result.goal_contract is not None
        assert result.goal_contract.weekly_hours == "6-10"
        assert result.goal_contract.target_role == "Senior GenAI"

    async def test_returns_active_contract_future_expires_at(
        self, pg_session: AsyncSession
    ) -> None:
        """Row with expires_at in the future is returned."""
        uid = uuid.uuid4()
        future = datetime.now(UTC) + timedelta(days=30)
        await _insert_contract(pg_session, uid, expires_at=future)

        result = await self._call(pg_session, uid)

        assert result.has_contract is True
        assert result.goal_contract is not None

    async def test_filters_expired_contract(
        self, pg_session: AsyncSession
    ) -> None:
        """Row with expires_at in the past is NOT returned (contract expired)."""
        uid = uuid.uuid4()
        past = datetime.now(UTC) - timedelta(hours=1)
        await _insert_contract(pg_session, uid, expires_at=past)

        result = await self._call(pg_session, uid)

        assert result.has_contract is False, (
            "Expired contract must be filtered — expires_at IS NULL OR > now() "
            "did not exclude a past-expired row"
        )
        assert result.goal_contract is None

    async def test_no_contract_returns_has_contract_false(
        self, pg_session: AsyncSession
    ) -> None:
        """User with no rows at all → has_contract=False."""
        uid = uuid.uuid4()
        result = await self._call(pg_session, uid)
        assert result.has_contract is False
        assert result.goal_contract is None


# ── study_planner / read_goal_contract ────────────────────────────────

class TestStudyPlannerReadGoalContract:
    """Pins the expires_at filter added at D12 CP3 Part D.2."""

    async def _call(self, session: AsyncSession, student_id: uuid.UUID) -> Any:
        from app.agents.tools.agent_specific.study_planner.read_goal_contract import (
            SpReadGoalContractInput,
            read_goal_contract,
        )

        token = _active_session.set(session)
        try:
            return await read_goal_contract(SpReadGoalContractInput(student_id=student_id))
        finally:
            _active_session.reset(token)

    async def test_returns_active_contract_null_expires_at(
        self, pg_session: AsyncSession
    ) -> None:
        """Row with NULL expires_at is returned."""
        uid = uuid.uuid4()
        await _insert_contract(pg_session, uid, expires_at=None)

        result = await self._call(pg_session, uid)

        assert result.has_contract is True
        assert result.goal_contract is not None
        assert result.goal_contract.weekly_hours == "6-10"
        assert result.goal_contract.target_role == "Senior GenAI"

    async def test_returns_active_contract_future_expires_at(
        self, pg_session: AsyncSession
    ) -> None:
        """Row with expires_at in the future is returned."""
        uid = uuid.uuid4()
        future = datetime.now(UTC) + timedelta(days=30)
        await _insert_contract(pg_session, uid, expires_at=future)

        result = await self._call(pg_session, uid)

        assert result.has_contract is True
        assert result.goal_contract is not None

    async def test_filters_expired_contract(
        self, pg_session: AsyncSession
    ) -> None:
        """Row with expires_at in the past is NOT returned."""
        uid = uuid.uuid4()
        past = datetime.now(UTC) - timedelta(hours=1)
        await _insert_contract(pg_session, uid, expires_at=past)

        result = await self._call(pg_session, uid)

        assert result.has_contract is False, (
            "Expired contract must be filtered — expires_at IS NULL OR > now() "
            "did not exclude a past-expired row"
        )
        assert result.goal_contract is None

    async def test_no_contract_returns_has_contract_false(
        self, pg_session: AsyncSession
    ) -> None:
        """User with no rows at all → has_contract=False."""
        uid = uuid.uuid4()
        result = await self._call(pg_session, uid)
        assert result.has_contract is False
        assert result.goal_contract is None
