"""Tests covering the agent_invocation_log dual-write window.

Specifically pinned cases (commit 0 review checklist):

  1. failed_counts_toward_quota — regression guard for the deliberate
     anti-spam logic. seed three GenerationLog rows with event='failed',
     assert quota_service counts them.
  2. cost_bearing_events_dual_write — completed/failed/cap_exceeded each
     append both a GenerationLog row AND an agent_invocation_log row.
  3. lifecycle_events_skip_dual_write — started/quota_blocked/downloaded
     write ONLY to GenerationLog. agent_invocation_log stays empty.
  4. parallel_quota_read_returns_identical — when the legacy and new
     tables agree on count, _count_events returns the (matching) value
     and the gate's consecutive_agreements counter advances.
  5. mock_dual_write — _log_cost writes to BOTH MockCostLog and
     agent_invocation_log on a successful turn.
  6. parity_gate_resets_on_divergence — when the two counts diverge,
     consecutive_agreements resets to 0 and the divergence payload is
     persisted on the gate row.
  7. parity_gate_flips_at_threshold — once AGREEMENT_THRESHOLD is hit,
     ``flipped`` becomes True and read paths can switch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_invocation_log import (
    QUOTA_CONSUMING_STATUSES,
    SOURCE_MOCK,
    SOURCE_RESUME,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    AgentInvocationLog,
)
from app.models.generation_log import GenerationLog
from app.models.interview_session import InterviewSession
from app.models.migration_gate import GATE_QUOTA_PARITY, MigrationGate
from app.models.mock_interview import MockCostLog
from app.models.user import User
from app.services.agent_invocation_logger import (
    AGREEMENT_THRESHOLD,
    has_flipped,
    log_invocation,
    record_parity_check,
)


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="Test User",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _seed_gate(db: AsyncSession) -> None:
    """Seed the migration_gates row that would normally be created by the
    alembic backfill. The test fixture builds tables via create_all, which
    does not run migration data steps."""
    db.add(
        MigrationGate(
            name=GATE_QUOTA_PARITY,
            consecutive_agreements=0,
            total_checks=0,
            total_divergences=0,
            flipped=False,
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# 1. failed_counts_toward_quota — regression guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_counts_toward_quota(db_session: AsyncSession) -> None:
    """Three failed generations consume three quota slots.

    This is a deliberate anti-spam rule, not a bug. If a future contributor
    "fixes" CONSUMING_EVENTS to drop 'failed', this test fails immediately.
    """
    from app.services.quota_service import _count_events_legacy

    user_id = await _make_user(db_session)
    now = datetime.now(UTC)
    for _ in range(3):
        db_session.add(
            GenerationLog(
                user_id=user_id, event="failed", created_at=now
            )
        )
    await db_session.commit()

    count = await _count_events_legacy(db_session, user_id=user_id)
    assert count == 3, (
        "failed events MUST count toward quota — see anti-spam comment in "
        "quota_service.py. Do NOT change CONSUMING_EVENTS without reading it."
    )


@pytest.mark.asyncio
async def test_failed_counts_toward_quota_in_new_table(
    db_session: AsyncSession,
) -> None:
    """Same regression guard, but on the new agent_invocation_log path.

    QUOTA_CONSUMING_STATUSES must include both 'succeeded' AND 'failed'.
    """
    from app.services.quota_service import _count_events_new

    user_id = await _make_user(db_session)
    for _ in range(3):
        await log_invocation(
            db_session,
            user_id=user_id,
            source=SOURCE_RESUME,
            source_id=None,
            sub_agent="tailoring_agent",
            model="claude-sonnet-4-6",
            tokens_in=100,
            tokens_out=50,
            cost_inr=2.5,
            status=STATUS_FAILED,
        )
    await db_session.commit()

    count = await _count_events_new(db_session, user_id=user_id)
    assert STATUS_FAILED in QUOTA_CONSUMING_STATUSES
    assert count == 3


# ---------------------------------------------------------------------------
# 2. cost-bearing events dual-write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_bearing_resume_event_dual_writes(
    db_session: AsyncSession,
) -> None:
    """tailored_resume_service._log_event with event='completed' must
    write rows to BOTH legacy and new tables in the same transaction."""
    from app.services.tailored_resume_service import _log_event

    user_id = await _make_user(db_session)
    await _log_event(
        db_session,
        user_id=user_id,
        event="completed",
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=400,
        cost_inr=4.5,
        latency_ms=2400,
    )

    legacy_count = (
        await db_session.execute(
            select(func.count())
            .select_from(GenerationLog)
            .where(GenerationLog.user_id == user_id)
        )
    ).scalar_one()
    new_count = (
        await db_session.execute(
            select(func.count())
            .select_from(AgentInvocationLog)
            .where(AgentInvocationLog.user_id == user_id)
        )
    ).scalar_one()

    assert legacy_count == 1
    assert new_count == 1


@pytest.mark.asyncio
async def test_failed_resume_event_dual_writes(
    db_session: AsyncSession,
) -> None:
    """The failure paths (CostCapExceededError, generic exception) hit the
    same _log_event path, so dual-write must fire on event='failed' too."""
    from app.services.tailored_resume_service import _log_event

    user_id = await _make_user(db_session)
    await _log_event(
        db_session,
        user_id=user_id,
        event="failed",
        cost_inr=1.2,
        error_message="LLM timeout",
    )

    new_rows = (
        await db_session.execute(
            select(AgentInvocationLog).where(
                AgentInvocationLog.user_id == user_id
            )
        )
    ).scalars().all()
    assert len(new_rows) == 1
    row = new_rows[0]
    assert row.status == STATUS_FAILED
    assert row.cost_inr == 1.2
    assert row.error_message == "LLM timeout"
    assert row.source == SOURCE_RESUME
    assert row.sub_agent == "tailoring_agent"


# ---------------------------------------------------------------------------
# 3. lifecycle events do NOT dual-write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_events_do_not_dual_write(
    db_session: AsyncSession,
) -> None:
    """started, quota_blocked, downloaded are lifecycle-only — they MUST
    NOT appear in agent_invocation_log."""
    from app.services.tailored_resume_service import _log_event

    user_id = await _make_user(db_session)
    for event in ("started", "quota_blocked", "downloaded"):
        await _log_event(db_session, user_id=user_id, event=event)

    legacy_count = (
        await db_session.execute(
            select(func.count())
            .select_from(GenerationLog)
            .where(GenerationLog.user_id == user_id)
        )
    ).scalar_one()
    new_count = (
        await db_session.execute(
            select(func.count())
            .select_from(AgentInvocationLog)
            .where(AgentInvocationLog.user_id == user_id)
        )
    ).scalar_one()

    assert legacy_count == 3
    assert new_count == 0, (
        "Lifecycle-only events must not pollute agent_invocation_log. "
        "If this fails, _EVENT_TO_STATUS in tailored_resume_service.py "
        "has a stray entry."
    )


# ---------------------------------------------------------------------------
# 4. parallel quota read agrees + advances counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_quota_read_returns_identical(
    db_session: AsyncSession,
) -> None:
    """When dual-write is working, _count_events_legacy and _count_events_new
    return identical values for the same user, and the gate counter
    advances on every check."""
    from app.services.quota_service import (
        _count_events,
        _count_events_legacy,
        _count_events_new,
    )
    from app.services.tailored_resume_service import _log_event

    await _seed_gate(db_session)
    user_id = await _make_user(db_session)

    for _ in range(2):
        await _log_event(
            db_session,
            user_id=user_id,
            event="completed",
            model="claude-sonnet-4-6",
            input_tokens=500,
            output_tokens=200,
            cost_inr=2.0,
        )

    legacy = await _count_events_legacy(db_session, user_id=user_id)
    new = await _count_events_new(db_session, user_id=user_id)
    assert legacy == new == 2

    # Calling the gated wrapper records a parity check.
    result = await _count_events(db_session, user_id=user_id)
    assert result == 2

    gate = (
        await db_session.execute(
            select(MigrationGate).where(MigrationGate.name == GATE_QUOTA_PARITY)
        )
    ).scalar_one()
    assert gate.consecutive_agreements >= 1
    assert gate.total_divergences == 0


# ---------------------------------------------------------------------------
# 5. mock interview dual-write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_log_cost_dual_writes(db_session: AsyncSession) -> None:
    """A successful mock interview turn writes to BOTH MockCostLog and
    agent_invocation_log."""
    from app.services.mock_interview_service import _log_cost

    user_id = await _make_user(db_session)
    session = InterviewSession(
        user_id=user_id,
        target_role="Junior Python Developer",
        level="junior",
        mode="behavioral",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    class _StubResponse:
        usage_metadata = {"input_tokens": 800, "output_tokens": 200}

    delta = await _log_cost(
        db_session,
        session=session,
        sub_agent="interviewer",
        response=_StubResponse(),
        latency_ms=1200,
        tier="fast",
    )
    assert delta >= 0  # cost is non-negative; exact value depends on pricing

    legacy_rows = (
        await db_session.execute(
            select(MockCostLog).where(MockCostLog.session_id == session.id)
        )
    ).scalars().all()
    new_rows = (
        await db_session.execute(
            select(AgentInvocationLog).where(
                AgentInvocationLog.source == SOURCE_MOCK,
                AgentInvocationLog.source_id == str(session.id),
            )
        )
    ).scalars().all()

    assert len(legacy_rows) == 1
    assert len(new_rows) == 1
    assert new_rows[0].user_id == user_id
    assert new_rows[0].sub_agent == "interviewer"
    assert new_rows[0].status == STATUS_SUCCEEDED


# ---------------------------------------------------------------------------
# 6. divergence resets the counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_gate_resets_on_divergence(
    db_session: AsyncSession,
) -> None:
    await _seed_gate(db_session)
    # Two agreements
    assert await record_parity_check(
        db_session, gate_name=GATE_QUOTA_PARITY, legacy_value=5, new_value=5
    ) is True
    assert await record_parity_check(
        db_session, gate_name=GATE_QUOTA_PARITY, legacy_value=6, new_value=6
    ) is True

    # Then a divergence
    agreed = await record_parity_check(
        db_session,
        gate_name=GATE_QUOTA_PARITY,
        legacy_value=7,
        new_value=6,
        context={"user_id": "abc"},
    )
    assert agreed is False

    gate = (
        await db_session.execute(
            select(MigrationGate).where(MigrationGate.name == GATE_QUOTA_PARITY)
        )
    ).scalar_one()
    assert gate.consecutive_agreements == 0
    assert gate.total_divergences == 1
    assert gate.flipped is False
    assert gate.last_divergence_payload is not None
    assert gate.last_divergence_payload.get("legacy") == 7
    assert gate.last_divergence_payload.get("new") == 6


# ---------------------------------------------------------------------------
# 7. flip after threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_gate_flips_at_threshold(
    db_session: AsyncSession,
) -> None:
    await _seed_gate(db_session)
    assert await has_flipped(db_session, gate_name=GATE_QUOTA_PARITY) is False

    for _ in range(AGREEMENT_THRESHOLD):
        await record_parity_check(
            db_session,
            gate_name=GATE_QUOTA_PARITY,
            legacy_value=42,
            new_value=42,
        )

    gate = (
        await db_session.execute(
            select(MigrationGate).where(MigrationGate.name == GATE_QUOTA_PARITY)
        )
    ).scalar_one()
    assert gate.consecutive_agreements >= AGREEMENT_THRESHOLD
    assert gate.flipped is True
    assert await has_flipped(db_session, gate_name=GATE_QUOTA_PARITY) is True
