"""D10 Checkpoint 1 — universal tool unit tests.

Covers:
  • Schema validation (input/output shapes, extra='forbid',
    cross-field invariants).
  • Tool registration (the registry actually picked up the five).
  • End-to-end behavior against a real MemoryStore via the
    pg_session fixture (Postgres + pgvector throwaway schema).
  • Error paths (missing session, ambiguous bulk-forget, capability
    not found).

The tools live at app/agents/tools/universal/. They use the
contextvar `_active_session` populated by call_agent in production;
these tests set it manually to drive the body without spinning a
full agent.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

# Importing the package side-effect-registers the tools.
import app.agents.tools  # noqa: F401  — populates registry
from app.agents.primitives import communication as comm_mod
from app.agents.primitives.tools import registry
from app.agents.tools.universal.log_event import (
    LogEventInput,
    LogEventOutput,
    log_event,
)
from app.agents.tools.universal.memory_forget import (
    MemoryForgetInput,
    MemoryForgetOutput,
    memory_forget,
)
from app.agents.tools.universal.memory_recall import (
    MemoryRecallInput,
    MemoryRecallOutput,
    memory_recall,
)
from app.agents.tools.universal.memory_write import (
    MemoryWriteInput,
    MemoryWriteOutput,
    memory_write,
)
from app.agents.tools.universal.read_own_capability import (
    ReadOwnCapabilityInput,
    ReadOwnCapabilityOutput,
    read_own_capability,
)

# pyproject.toml sets asyncio_mode = "auto", so async test funcs run
# under pytest-asyncio without an explicit mark; sync funcs run as
# regular tests. Mixing both in one file just works.


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_on_contextvar(pg_session: AsyncSession):
    """Set the contextvar before each test, reset after.

    Universal tool bodies recover their session via
    `get_active_session()`. In production, call_agent does this; in
    tests we do it directly so we can drive a tool body without
    spinning a full agent.
    """
    token = comm_mod._active_session.set(pg_session)
    try:
        yield pg_session
    finally:
        comm_mod._active_session.reset(token)


def _user_id() -> uuid.UUID:
    return uuid.uuid4()


# ── Registry visibility ─────────────────────────────────────────────


def test_all_five_universal_tools_register() -> None:
    """The registry sees all five universal tools by name after the
    package import has fired its decorators."""
    names = registry.names()
    for expected in (
        "memory_recall",
        "memory_write",
        "memory_forget",
        "log_event",
        "read_own_capability",
    ):
        assert expected in names, (
            f"{expected!r} not registered. Got: {names!r}"
        )


def test_d3_memory_stubs_no_longer_register() -> None:
    """D10 retired the D3 stubs `recall_memory` / `store_memory` by
    removing memory_tools from the package's import block. The
    registry should not see them anymore — otherwise we have dead
    NotImplementedError-raisers competing with the real universal
    tools."""
    names = registry.names()
    assert "recall_memory" not in names, (
        "D3 stub recall_memory should no longer register; D10 "
        "supersedes it with memory_recall."
    )
    assert "store_memory" not in names, (
        "D3 stub store_memory should no longer register; D10 "
        "supersedes it with memory_write."
    )


# ── Schema validation ───────────────────────────────────────────────


def test_memory_recall_input_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MemoryRecallInput(query="foo", bogus="bar")  # type: ignore[call-arg]


def test_memory_recall_input_caps_query_length() -> None:
    with pytest.raises(ValidationError):
        MemoryRecallInput(query="x" * 2001)


def test_memory_recall_input_caps_k() -> None:
    with pytest.raises(ValidationError):
        MemoryRecallInput(query="ok", k=51)
    with pytest.raises(ValidationError):
        MemoryRecallInput(query="ok", k=0)


def test_memory_write_input_requires_agent_name() -> None:
    with pytest.raises(ValidationError):
        MemoryWriteInput(  # type: ignore[call-arg]
            user_id=_user_id(), key="k", value={}
        )


def test_memory_write_input_caps_valence_range() -> None:
    with pytest.raises(ValidationError):
        MemoryWriteInput(
            agent_name="x", key="k", value={}, valence=1.5,
        )


def test_memory_forget_input_requires_exactly_one_target() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        MemoryForgetInput(confirm=True)  # nothing to forget
    with pytest.raises(ValidationError, match="exactly one"):
        MemoryForgetInput(
            memory_id=uuid.uuid4(),
            user_id=_user_id(),
            confirm=True,
        )


def test_memory_forget_bulk_paths_require_confirm() -> None:
    """The Pass 3d §D.3 safety guard: bulk wipes need confirm=True."""
    with pytest.raises(ValidationError, match="confirm=True"):
        MemoryForgetInput(user_id=_user_id())  # confirm defaults False
    with pytest.raises(ValidationError, match="confirm=True"):
        MemoryForgetInput(key_pattern="pref:%")


def test_memory_forget_single_row_does_not_need_confirm() -> None:
    """The single-id path stays ergonomic — no confirm required for
    a precise targeted delete."""
    parsed = MemoryForgetInput(memory_id=uuid.uuid4())
    assert parsed.confirm is False  # default; that's fine for single-id


def test_log_event_validates_event_name_pattern() -> None:
    """The dotted-lowercase regex from Pass 3d §D.4."""
    LogEventInput(event_name="tutor.breakthrough", properties={})
    with pytest.raises(ValidationError, match="event_name"):
        LogEventInput(event_name="NoDots", properties={})
    with pytest.raises(ValidationError, match="event_name"):
        LogEventInput(event_name="too.many.dots", properties={})
    with pytest.raises(ValidationError, match="event_name"):
        LogEventInput(event_name="UPPER.case", properties={})


# ── Missing-session guards (Class A failure) ───────────────────────


async def test_memory_recall_raises_without_active_session() -> None:
    """Defensive: tool bodies surface the missing-session bug loudly.
    Production never hits this path (call_agent sets the contextvar)
    but tests that forget to set it should fail fast."""
    # No fixture that sets the contextvar; intentionally bare.
    with pytest.raises(RuntimeError, match="active session"):
        await memory_recall(MemoryRecallInput(query="anything"))


async def test_memory_write_raises_without_active_session() -> None:
    with pytest.raises(RuntimeError, match="active session"):
        await memory_write(
            MemoryWriteInput(agent_name="x", key="k", value={"a": 1})
        )


async def test_memory_forget_raises_without_active_session() -> None:
    with pytest.raises(RuntimeError, match="active session"):
        await memory_forget(MemoryForgetInput(memory_id=uuid.uuid4()))


# ── Round-trip: write → recall → forget against real Postgres ──────


async def test_memory_write_creates_row(
    session_on_contextvar: AsyncSession,
    voyage_disabled: None,
) -> None:
    user = _user_id()
    out = await memory_write(
        MemoryWriteInput(
            user_id=user,
            agent_name="billing_support",
            scope="user",
            key="pref:billing_communication_tone",
            value={"tone": "warm but professional"},
        )
    )
    assert isinstance(out, MemoryWriteOutput)
    assert out.was_update is False  # fresh write
    # Confirm landed on disk.
    raw = await session_on_contextvar.execute(
        sql_text("SELECT count(*) FROM agent_memory WHERE user_id = :uid"),
        {"uid": user},
    )
    assert raw.scalar_one() == 1


async def test_memory_write_is_idempotent_on_repeat_key(
    session_on_contextvar: AsyncSession,
    voyage_disabled: None,
) -> None:
    """Same (user, agent, scope, key) → in-place update, was_update=True
    on the second call."""
    user = _user_id()
    base = MemoryWriteInput(
        user_id=user,
        agent_name="billing_support",
        scope="user",
        key="pref:contact_window",
        value={"window": "mornings"},
    )
    first = await memory_write(base)
    second = await memory_write(
        base.model_copy(update={"value": {"window": "evenings"}})
    )
    assert first.was_update is False
    assert second.was_update is True
    assert first.memory_id == second.memory_id  # same row updated


async def test_memory_recall_returns_written_row(
    session_on_contextvar: AsyncSession,
    voyage_disabled: None,
) -> None:
    """Write a row, then recall by structured key match. Hybrid mode
    catches both semantic and substring hits, which is what agents
    use in production."""
    user = _user_id()
    await memory_write(
        MemoryWriteInput(
            user_id=user,
            agent_name="billing_support",
            scope="user",
            key="interaction:billing_concern:2026-04-30",
            value={
                "summary": "Asked about delayed refund on order CF-123.",
                "resolved": True,
            },
        )
    )
    out = await memory_recall(
        MemoryRecallInput(
            query="billing_concern",
            user_id=user,
            agent_name="billing_support",
            scope="user",
            mode="structured",
            k=5,
        )
    )
    assert isinstance(out, MemoryRecallOutput)
    assert len(out.memories) == 1
    hit = out.memories[0]
    assert hit.key == "interaction:billing_concern:2026-04-30"
    assert hit.value["resolved"] is True


async def test_memory_recall_empty_when_nothing_matches(
    session_on_contextvar: AsyncSession,
    voyage_disabled: None,
) -> None:
    out = await memory_recall(
        MemoryRecallInput(
            query="never-written-key",
            user_id=_user_id(),
            agent_name="billing_support",
            scope="user",
            mode="structured",
        )
    )
    assert out.memories == []


async def test_memory_forget_single_row(
    session_on_contextvar: AsyncSession,
    voyage_disabled: None,
) -> None:
    user = _user_id()
    written = await memory_write(
        MemoryWriteInput(
            user_id=user,
            agent_name="billing_support",
            scope="user",
            key="interaction:billing_concern:2026-04-30",
            value={"summary": "to be forgotten"},
        )
    )
    out = await memory_forget(MemoryForgetInput(memory_id=written.memory_id))
    assert isinstance(out, MemoryForgetOutput)
    assert out.forgotten_count == 1
    # Confirm gone.
    raw = await session_on_contextvar.execute(
        sql_text("SELECT count(*) FROM agent_memory WHERE id = :mid"),
        {"mid": written.memory_id},
    )
    assert raw.scalar_one() == 0


async def test_memory_forget_bulk_by_user(
    session_on_contextvar: AsyncSession,
    voyage_disabled: None,
) -> None:
    user = _user_id()
    for i in range(3):
        await memory_write(
            MemoryWriteInput(
                user_id=user,
                agent_name="billing_support",
                scope="user",
                key=f"pref:thing_{i}",
                value={"i": i},
            )
        )
    out = await memory_forget(
        MemoryForgetInput(user_id=user, confirm=True)
    )
    assert out.forgotten_count == 3


async def test_memory_forget_missing_row_is_zero_not_error(
    session_on_contextvar: AsyncSession,
) -> None:
    out = await memory_forget(MemoryForgetInput(memory_id=uuid.uuid4()))
    assert out.forgotten_count == 0


# ── log_event: structlog routing ────────────────────────────────────


async def test_log_event_returns_logged_true() -> None:
    """log_event needs no session; just emits via structlog. We
    confirm the contract: legal input → logged=True."""
    out = await log_event(
        LogEventInput(
            event_name="tutor.student_breakthrough",
            properties={"student_id": "abc", "concept": "RAG"},
            severity="info",
        )
    )
    assert isinstance(out, LogEventOutput)
    assert out.logged is True


async def test_log_event_severity_routes_to_correct_method() -> None:
    """Each declared severity level resolves to a structlog method."""
    for sev in ("debug", "info", "warning", "error"):
        out = await log_event(
            LogEventInput(
                event_name="agent.test_event",
                properties={"sev": sev},
                severity=sev,  # type: ignore[arg-type]
            )
        )
        assert out.logged is True


# ── read_own_capability: registry lookup ───────────────────────────


async def test_read_own_capability_finds_billing_support() -> None:
    """billing_support was declared in capability.py; the lookup
    should return its full AgentCapability."""
    out = await read_own_capability(
        ReadOwnCapabilityInput(agent_name="billing_support")
    )
    assert isinstance(out, ReadOwnCapabilityOutput)
    assert out.found is True
    assert out.capability is not None
    assert out.capability.name == "billing_support"
    assert out.capability.minimum_tier == "free"
    # D10 contract: billing_support is now available_now=True
    assert out.capability.available_now is True


async def test_read_own_capability_missing_returns_none() -> None:
    """Unknown agent name returns found=False rather than raising."""
    out = await read_own_capability(
        ReadOwnCapabilityInput(agent_name="not_a_real_agent_xyz")
    )
    assert out.found is False
    assert out.capability is None
