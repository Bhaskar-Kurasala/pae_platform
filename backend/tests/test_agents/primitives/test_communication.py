"""Inter-agent communication — `call_agent`, cycle detection, depth.

Postgres-backed; uses the per-test schema fixture from conftest. The
`agent_call_chain` table is created on demand inside each test that
needs to inspect audit rows (mirrors the test_tools.py pattern).

Mock callees implement the AgenticCallee protocol with a tiny
`run_agentic` that records what it received and optionally calls
through to another agent. That keeps the tests deterministic without
spinning up the real LLM-backed agents.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import (
    AgentCallResult,
    AgentNotFoundError,
    AgentPermissionError,
    CallChain,
    CallDepthExceededError,
    CycleDetectedError,
    call_agent,
    clear_agentic_registry,
    register_agentic,
)


pytestmark = pytest.mark.asyncio


# ── Test fixtures ───────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_agentic_registry() -> AsyncGenerator[None, None]:
    """Each test starts with an empty agentic registry. There are no
    production agentic agents to reload yet (D7 lands them); tests
    register their own mocks inline.

    Same reload-at-setup philosophy as the tool registry — clear at
    setup so the test body sees the state it expects, clear again at
    teardown so the next test isn't poisoned by leftovers.
    """
    clear_agentic_registry()
    yield
    clear_agentic_registry()


@pytest_asyncio.fixture
async def chain_table(pg_session: AsyncSession) -> AsyncSession:
    """Create the agent_call_chain table in the per-test schema.

    The conftest fixture only creates agent_memory; this test file
    adds agent_call_chain on demand. Same shape as the migration's
    table so any insert SQLAlchemy emits lines up with what prod
    sees.
    """
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_call_chain (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                root_id UUID NOT NULL,
                parent_id UUID,
                caller_agent TEXT,
                callee_agent TEXT NOT NULL,
                depth INT NOT NULL DEFAULT 0,
                payload JSONB,
                result JSONB,
                status TEXT NOT NULL,
                user_id UUID,
                duration_ms INT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT agent_call_chain_status_chk CHECK (
                    status IN ('ok','error','cycle','depth_exceeded')
                ),
                CONSTRAINT agent_call_chain_depth_nonneg CHECK (depth >= 0)
            )
            """
        )
    )
    await pg_session.commit()
    return pg_session


# ── Mock callee ─────────────────────────────────────────────────────


@dataclass
class MockCallee:
    """Lightweight mock of AgenticCallee.

    The `behavior` callable receives `(payload, chain, session)` and
    returns the AgentCallResult to surface. Tests parametrise it to
    simulate ok / raise / nested-call paths.

    The session field carries the live test session so behaviors can
    fire nested call_agent invocations against the same DB.
    """

    name: str
    behavior: Callable[
        [Any, CallChain, AsyncSession],
        Awaitable[AgentCallResult],
    ]
    session: AsyncSession | None = None
    allowed_callers: tuple[str, ...] = ()
    allowed_callees: tuple[str, ...] = ()
    received_payloads: list[Any] = field(default_factory=list)
    received_chains: list[CallChain] = field(default_factory=list)

    async def run_agentic(
        self, payload: Any, chain: CallChain
    ) -> AgentCallResult:
        self.received_payloads.append(payload)
        self.received_chains.append(chain)
        return await self.behavior(payload, chain, self.session)


def _ok_result(callee: str, *, output: dict[str, Any] | None = None) -> AgentCallResult:
    return AgentCallResult(
        callee=callee,
        output=output or {"ok": True},
        status="ok",
        duration_ms=0,
    )


# ── Root-id contract (the D4 directive) ─────────────────────────────


async def test_root_id_is_set_on_depth_zero_single_call(
    chain_table: AsyncSession,
) -> None:
    """The trace must be recoverable via `WHERE root_id = X` even
    when the chain didn't recurse. This is the load-bearing
    observability invariant for D4."""

    async def _just_ok(_payload: Any, _chain: CallChain, _s: Any) -> AgentCallResult:
        return _ok_result("solo")

    register_agentic(MockCallee(name="solo", behavior=_just_ok))
    chain = CallChain.start_root(caller="moa")
    result = await call_agent(
        "solo",
        payload={"x": 1},
        session=chain_table,
        chain=chain,
    )
    assert result.status == "ok"
    assert result.root_id == chain.root_id
    assert result.chain_id is not None

    raw = await chain_table.execute(
        sql_text("SELECT root_id, parent_id, depth, status FROM agent_call_chain")
    )
    rows = raw.all()
    assert len(rows) == 1
    row_root, row_parent, row_depth, row_status = rows[0]
    assert row_root == chain.root_id
    assert row_parent is None
    # Root depth = 1 (the link from <root> caller to the callee is
    # the first hop). Tests for nested calls below confirm depth
    # increments correctly.
    assert row_depth == 1
    assert row_status == "ok"


async def test_root_id_propagates_through_nested_chain(
    chain_table: AsyncSession,
) -> None:
    """A→B→C: the same root_id appears on all three audit rows."""
    sentinel = {"chain_seen_by_C": None}

    async def _c_behavior(_payload: Any, chain: CallChain, _s: Any) -> AgentCallResult:
        sentinel["chain_seen_by_C"] = chain
        return _ok_result("C")

    async def _b_behavior(_payload: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        nested = await call_agent(
            "C",
            payload={"from": "B"},
            session=sess,
            chain=chain,
        )
        assert nested.status == "ok"
        return _ok_result("B", output={"got_C_root": str(nested.root_id)})

    async def _a_behavior(_payload: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        nested = await call_agent(
            "B",
            payload={"from": "A"},
            session=sess,
            chain=chain,
        )
        assert nested.status == "ok"
        return _ok_result("A", output={"got_B": nested.output})

    register_agentic(MockCallee(name="C", behavior=_c_behavior, session=chain_table))
    register_agentic(MockCallee(name="B", behavior=_b_behavior, session=chain_table))
    register_agentic(MockCallee(name="A", behavior=_a_behavior, session=chain_table))

    chain = CallChain.start_root(caller="moa")
    result = await call_agent(
        "A",
        payload={"start": True},
        session=chain_table,
        chain=chain,
    )
    assert result.status == "ok"

    raw = await chain_table.execute(
        sql_text(
            "SELECT root_id, callee_agent, depth, status "
            "FROM agent_call_chain ORDER BY depth, callee_agent"
        )
    )
    rows = raw.all()
    assert len(rows) == 3, f"expected 3 audit rows, got {len(rows)}"
    # All three rows share the same root_id.
    assert {r[0] for r in rows} == {chain.root_id}
    # Depths increment 1 → 2 → 3. (Depth-of-link convention; root
    # caller is `<root>`, so the first link is depth 1.)
    assert [r[2] for r in rows] == [1, 2, 3]
    assert {r[3] for r in rows} == {"ok"}
    # And each callee got the same root_id in the chain it received.
    chain_at_C = sentinel["chain_seen_by_C"]
    assert chain_at_C is not None
    assert chain_at_C.root_id == chain.root_id


# ── Cycle detection ─────────────────────────────────────────────────


async def test_cycle_a_to_b_to_a_raises_and_audits(
    chain_table: AsyncSession,
) -> None:
    """A→B→A is a cycle: B's nested call to A must raise
    CycleDetectedError. The audit row for that failed link is
    still written with status='cycle' so the trace is recoverable."""

    async def _a_first_call(_p: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        # On first invocation, A calls B.
        return await call_agent(
            "B", payload={}, session=sess, chain=chain
        )

    async def _b_calls_a_back(_p: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        # B tries to call A — should trip the cycle detector.
        # We let CycleDetectedError propagate; the outer call_agent
        # at A will see it as a nested CommunicationError and
        # re-raise after writing its own audit row.
        return await call_agent(
            "A", payload={}, session=sess, chain=chain
        )

    register_agentic(MockCallee(name="A", behavior=_a_first_call, session=chain_table))
    register_agentic(MockCallee(name="B", behavior=_b_calls_a_back, session=chain_table))

    chain = CallChain.start_root(caller="moa")
    with pytest.raises(CycleDetectedError) as exc_info:
        await call_agent("A", payload={}, session=chain_table, chain=chain)

    assert hasattr(exc_info.value, "chain_id")
    assert exc_info.value.root_id == chain.root_id

    # Audit rows: outer A → B (error after nested cycle bubbled),
    # then B → A (this attempt to call A back recurses one level
    # before tripping the (A, B) edge guard inside the second A).
    # Concretely: the cycle is detected when A's second invocation
    # tries to call B again — the (A, B) edge is already on the
    # chain from the first descent. So the row that lands with
    # status='cycle' has callee_agent='B', not 'A'. Subtle but
    # correct: cycles are detected at the edge that closes the
    # loop, and that's whichever edge would re-traverse a pair
    # already visited.
    raw = await chain_table.execute(
        sql_text(
            "SELECT callee_agent, status FROM agent_call_chain "
            "ORDER BY depth"
        )
    )
    rows = raw.all()
    statuses = {r[1] for r in rows}
    assert "cycle" in statuses, (
        f"expected exactly one cycle audit row, got rows={list(rows)}"
    )
    cycle_count = sum(1 for r in rows if r[1] == "cycle")
    assert cycle_count == 1


async def test_cycle_does_not_block_diamonds(
    chain_table: AsyncSession,
) -> None:
    """Diamond shape: A→B and A→C, both ending at D. NOT a cycle."""

    async def _d(_p: Any, _chain: CallChain, _s: Any) -> AgentCallResult:
        return _ok_result("D")

    async def _b(_p: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        await call_agent("D", payload={}, session=sess, chain=chain)
        return _ok_result("B")

    async def _c(_p: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        await call_agent("D", payload={}, session=sess, chain=chain)
        return _ok_result("C")

    async def _a(_p: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        await call_agent("B", payload={}, session=sess, chain=chain)
        await call_agent("C", payload={}, session=sess, chain=chain)
        return _ok_result("A")

    for name, beh in (("A", _a), ("B", _b), ("C", _c), ("D", _d)):
        register_agentic(MockCallee(name=name, behavior=beh, session=chain_table))

    chain = CallChain.start_root(caller="moa")
    result = await call_agent("A", payload={}, session=chain_table, chain=chain)
    assert result.status == "ok"
    raw = await chain_table.execute(
        sql_text("SELECT count(*) FROM agent_call_chain WHERE status = 'ok'")
    )
    # 5 successful links: A, B, B→D, C, C→D.
    assert raw.scalar_one() == 5


# ── Depth ceiling ───────────────────────────────────────────────────


async def test_depth_exceeded_raises_at_the_ceiling(
    chain_table: AsyncSession,
) -> None:
    """Build a 6-deep chain; with max_depth=5 the 6th call must
    raise CallDepthExceededError. The cap is configurable via
    CallChain.start_root(max_depth=...)."""

    async def _make_recurser(
        next_callee: str | None,
    ) -> Callable[[Any, CallChain, Any], Awaitable[AgentCallResult]]:
        async def _b(_p: Any, chain: CallChain, sess: Any) -> AgentCallResult:
            if next_callee is not None:
                await call_agent(next_callee, payload={}, session=sess, chain=chain)
            return _ok_result("recurser")
        return _b

    # Chain of A→B→C→D→E→F→G — 7 levels deep.
    names = ["A", "B", "C", "D", "E", "F", "G"]
    for i, name in enumerate(names):
        target = names[i + 1] if i + 1 < len(names) else None
        register_agentic(
            MockCallee(name=name, behavior=await _make_recurser(target), session=chain_table)
        )

    # max_depth=5 → 5 successful links allowed; the 6th raises.
    chain = CallChain.start_root(caller="moa", max_depth=5)
    with pytest.raises(CallDepthExceededError) as exc_info:
        await call_agent("A", payload={}, session=chain_table, chain=chain)
    assert exc_info.value.root_id == chain.root_id

    raw = await chain_table.execute(
        sql_text(
            "SELECT count(*) FROM agent_call_chain "
            "WHERE status = 'depth_exceeded'"
        )
    )
    assert raw.scalar_one() == 1


# ── Agent-not-found ─────────────────────────────────────────────────


async def test_unknown_agent_raises_and_audits(
    chain_table: AsyncSession,
) -> None:
    chain = CallChain.start_root(caller="moa")
    with pytest.raises(AgentNotFoundError) as exc_info:
        await call_agent(
            "phantom", payload={}, session=chain_table, chain=chain
        )
    assert exc_info.value.root_id == chain.root_id

    raw = await chain_table.execute(
        sql_text(
            "SELECT callee_agent, status FROM agent_call_chain"
        )
    )
    rows = raw.all()
    assert rows == [("phantom", "error")]


# ── Permission checks ───────────────────────────────────────────────


async def test_callee_blocks_unlisted_caller(
    chain_table: AsyncSession,
) -> None:
    """Callee with non-empty `allowed_callers` rejects everyone else."""

    async def _privileged(_p: Any, _c: CallChain, _s: Any) -> AgentCallResult:
        return _ok_result("privileged")

    register_agentic(
        MockCallee(
            name="privileged",
            behavior=_privileged,
            allowed_callers=("admin_only",),
        )
    )

    chain = CallChain.start_root(caller="moa")
    with pytest.raises(AgentPermissionError) as exc_info:
        await call_agent(
            "privileged", payload={}, session=chain_table, chain=chain
        )
    assert "moa" in str(exc_info.value)
    assert exc_info.value.root_id == chain.root_id


async def test_callee_allows_listed_caller(
    chain_table: AsyncSession,
) -> None:
    async def _privileged(_p: Any, _c: CallChain, _s: Any) -> AgentCallResult:
        return _ok_result("privileged")

    register_agentic(
        MockCallee(
            name="privileged",
            behavior=_privileged,
            allowed_callers=("admin_only", "moa"),
        )
    )
    chain = CallChain.start_root(caller="moa")
    result = await call_agent(
        "privileged", payload={}, session=chain_table, chain=chain
    )
    assert result.status == "ok"


async def test_caller_allowed_callees_enforced(
    chain_table: AsyncSession,
) -> None:
    """A caller with non-empty allowed_callees can ONLY call those."""

    async def _benign(_p: Any, _c: CallChain, _s: Any) -> AgentCallResult:
        return _ok_result("benign")

    async def _restricted(_p: Any, chain: CallChain, sess: Any) -> AgentCallResult:
        # Tries to call a callee not in its allow-list.
        return await call_agent(
            "off_limits", payload={}, session=sess, chain=chain
        )

    register_agentic(MockCallee(name="benign", behavior=_benign))
    register_agentic(MockCallee(name="off_limits", behavior=_benign))
    register_agentic(
        MockCallee(
            name="restricted",
            behavior=_restricted,
            allowed_callees=("benign",),
            session=chain_table,
        )
    )

    chain = CallChain.start_root(caller="moa")
    with pytest.raises(AgentPermissionError):
        await call_agent(
            "restricted", payload={}, session=chain_table, chain=chain
        )


# ── Callee-raises path ──────────────────────────────────────────────


async def test_callee_runtime_exception_returns_error_result(
    chain_table: AsyncSession,
) -> None:
    """Generic exceptions in run_agentic become status='error'
    AgentCallResult — not raised. This is the non-fatal failure
    mode the protocol commits to."""

    async def _explody(_p: Any, _c: CallChain, _s: Any) -> AgentCallResult:
        raise RuntimeError("kaboom")

    register_agentic(MockCallee(name="explody", behavior=_explody))
    chain = CallChain.start_root(caller="moa")
    result = await call_agent(
        "explody", payload={}, session=chain_table, chain=chain
    )
    assert result.status == "error"
    assert "RuntimeError" in (result.error or "")
    assert result.chain_id is not None
    assert result.root_id == chain.root_id

    raw = await chain_table.execute(
        sql_text(
            "SELECT status, result FROM agent_call_chain "
            "WHERE callee_agent = 'explody'"
        )
    )
    row = raw.one()
    assert row[0] == "error"
    # Error message stashed in the result jsonb so the audit row
    # carries the diagnosis without a schema bump.
    assert row[1] is not None and "kaboom" in str(row[1])


# ── Timeout path ────────────────────────────────────────────────────


async def test_callee_timeout_returns_timeout_result(
    chain_table: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callee that exceeds agent_call_timeout_seconds → status='timeout'.

    We monkeypatch the ceiling down to ~0.05s so the test runs
    quickly. The audit row is still written with status='error'
    (timeout collapses to error in the schema; the result jsonb
    carries the 'timeout after Xs' marker)."""
    monkeypatch.setattr(
        "app.agents.primitives.communication.settings.agent_call_timeout_seconds",
        0.05,
        raising=False,
    )

    async def _slow(_p: Any, _c: CallChain, _s: Any) -> AgentCallResult:
        await asyncio.sleep(1.0)
        return _ok_result("slow")

    register_agentic(MockCallee(name="slow", behavior=_slow))
    chain = CallChain.start_root(caller="moa")
    result = await call_agent(
        "slow", payload={}, session=chain_table, chain=chain
    )
    assert result.status == "timeout"
    assert "timeout" in (result.error or "").lower()
    assert result.root_id == chain.root_id

    raw = await chain_table.execute(
        sql_text("SELECT status, result FROM agent_call_chain")
    )
    row = raw.one()
    assert row[0] == "error"
    assert "timeout" in str(row[1]).lower()
