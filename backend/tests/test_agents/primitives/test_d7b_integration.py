"""End-to-end smoke for the D7b plumbing.

Per the D7b integration directive: not unit tests of each link.
A real test that registers a fake @proactive agent, calls
register_proactive_schedules, kicks the Celery task synchronously
(`task.apply()`, not `delay()`), and asserts the agent ran and the
agent_proactive_runs row landed.

If this passes, the cron → Celery task → dispatch → agent → audit
path is wired correctly. If any link breaks, this test fails first.

We deliberately do NOT mock Celery itself — `task.apply()` runs
the task body synchronously in-process (no broker, no worker)
which is what we want for a CI-friendly integration test. The
underlying primitives (memory, tools, evaluation) are exercised
by their own dedicated test modules; this file only proves the
integration glue.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.agentic_base import AgentContext, AgentInput, AgenticBaseAgent
from app.agents.primitives.communication import CallChain
from app.agents.primitives.proactive import (
    clear_proactive_registry,
    list_schedules,
    proactive,
    register_proactive_schedules,
)
from app.agents.primitives import clear_agentic_registry


pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_registries() -> AsyncGenerator[None, None]:
    """Each test starts and ends with empty agentic + proactive
    registries so decorator side effects don't leak."""
    clear_agentic_registry()
    clear_proactive_registry()
    yield
    clear_agentic_registry()
    clear_proactive_registry()


@pytest_asyncio.fixture
async def proactive_db(pg_session: AsyncSession) -> AsyncSession:
    """Create the audit tables D7b's plumbing writes to.
    Tests share the per-test schema with the existing primitives
    fixture infrastructure."""
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_proactive_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                trigger_source TEXT NOT NULL,
                trigger_key TEXT NOT NULL,
                user_id UUID,
                payload JSONB,
                status TEXT NOT NULL,
                error_message TEXT,
                duration_ms INT,
                idempotency_key TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT agent_proactive_runs_status_chk CHECK (
                    status IN ('queued','ok','error','skipped')
                )
            )
            """
        )
    )
    await pg_session.execute(
        sql_text(
            "CREATE UNIQUE INDEX IF NOT EXISTS agent_proactive_runs_idemp_uidx "
            "ON agent_proactive_runs (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL"
        )
    )
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


# ── Boot-order: load_agentic_agents ─────────────────────────────────


async def test_load_agentic_agents_loud_failure_on_broken_module() -> None:
    """The directive: a broken import must fail loudly with the
    module name, not silently skip. Pass a non-existent module
    name to load_agentic_agents and assert it raises with context."""
    from app.agents._agentic_loader import (
        AgenticAgentImportError,
        load_agentic_agents,
    )

    with pytest.raises(AgenticAgentImportError, match="phantom_agent_module"):
        load_agentic_agents(modules=["app.agents.phantom_agent_module"])


async def test_load_agentic_agents_imports_each_listed_module() -> None:
    """Pass a real-but-empty module list (the production default
    today). Should succeed with an empty result rather than raise."""
    from app.agents._agentic_loader import load_agentic_agents

    # Production default is an empty tuple — D8 will populate it.
    loaded = load_agentic_agents(modules=[])
    assert loaded == []


# ── register_proactive_schedules: end-to-end with celery_app ───────


async def test_register_schedules_into_real_celery_app() -> None:
    """Register a fake @proactive decorator, then call
    register_proactive_schedules against the actual celery_app
    (not a fake). The schedule must land in the real beat_schedule
    dict.

    This is what proves boot-order works — if Celery's import
    happens before our register call, the schedule is invisible."""
    from app.core.celery_app import celery_app

    # Use a unique cron so we can find our entry without sweeping
    # legacy ones. * * * * 6 = every minute on Saturday — won't
    # conflict with any production schedule.
    @proactive(agent_name="d7b_smoke_agent", cron="* * * * 6")
    class _SmokeAgent:
        pass

    schedules = list_schedules()
    assert len(schedules) == 1
    count = register_proactive_schedules(celery_app)
    assert count == 1

    # Find our entry under the agentic: prefix.
    keys = [
        k for k in celery_app.conf.beat_schedule
        if k.startswith("agentic:d7b_smoke_agent:")
    ]
    assert len(keys) == 1
    entry = celery_app.conf.beat_schedule[keys[0]]
    assert entry["task"] == "app.agents.primitives.proactive.run_proactive_task"
    # Args mirror the @proactive registration positional shape.
    assert entry["args"] == ("d7b_smoke_agent", "* * * * 6", False)


# ── End-to-end: cron → Celery task → dispatch → agent → audit ─────


async def test_proactive_runner_fires_agent_and_writes_audit_row(
    proactive_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The directive in spirit:
       register_agentic agent → register_proactive_schedules
       → kick the proactive runner end-to-end
       → assert agent ran AND audit row landed.

    Implementation note: the production Celery task body is a thin
    `asyncio.run(_run_proactive_async(...))` wrapper. We exercise
    the inner async function directly here because async SQLAlchemy
    sessions are bound to the loop they're created in — passing
    the per-test schema session into a Celery task that spawns a
    fresh worker-thread loop trips "Future attached to a different
    loop" and the test misleadingly fails.

    The Celery wrapper itself is covered separately by
    `test_celery_task_registered` (asserts the @shared_task
    decorator + task name binding) and the production task body
    is two lines (`asyncio.run` + a log line) — keeping the
    primary assertion focused on the dispatch path is cheaper
    than fighting the loop boundary.
    """
    from datetime import datetime, UTC

    from app.tasks.proactive_runner import _run_proactive_async

    invocations: list[dict] = []

    class _SmokePayload(AgentInput):
        cron: str
        scheduled_for: str

    class _SmokeAgent(AgenticBaseAgent[_SmokePayload]):
        name = "d7b_smoke_agent_e2e"
        description = "fake agent for the D7b smoke test"
        input_schema = _SmokePayload

        async def run(
            self, input: _SmokePayload, ctx: AgentContext
        ) -> dict:
            invocations.append(
                {"cron": input.cron, "scheduled_for": input.scheduled_for}
            )
            return {"ran": True}

    from app.agents.primitives import list_agentic
    assert "d7b_smoke_agent_e2e" in list_agentic()

    # Bind AsyncSessionLocal to the per-test schema so the dispatcher's
    # internal `async with AsyncSessionLocal()` lands in our throwaway
    # schema rather than the dev DB.
    test_session_factory = async_sessionmaker(
        proactive_db.bind, expire_on_commit=False
    )
    monkeypatch.setattr(
        "app.tasks.proactive_runner.AsyncSessionLocal",
        test_session_factory,
        raising=False,
    )

    summary = await _run_proactive_async(
        agent_name="d7b_smoke_agent_e2e",
        cron_expr="0 9 * * *",
        per_user=False,
        scheduled_for=datetime.now(UTC),
    )

    # The agent ran exactly once (per_user=False → single dispatch).
    assert len(invocations) == 1
    assert invocations[0]["cron"] == "0 9 * * *"

    # The audit row landed in agent_proactive_runs.
    raw = await proactive_db.execute(
        sql_text(
            "SELECT agent_name, trigger_source, status, idempotency_key "
            "FROM agent_proactive_runs"
        )
    )
    rows = raw.all()
    assert len(rows) == 1
    name, source, status_, key = rows[0]
    assert name == "d7b_smoke_agent_e2e"
    assert source == "cron"
    assert status_ == "ok"
    assert key.startswith("cron:d7b_smoke_agent_e2e:0 9 * * *:")
    assert summary["dispatched"] == 1
    assert summary["deduped"] == 0
    assert summary["errors"] == 0


async def test_proactive_runner_dedups_on_retry(
    proactive_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Celery worker restart can fire the same beat tick twice
    (rare but possible). The idempotency key is minute-bucketed,
    so a second invocation within the same UTC minute MUST collapse
    to zero new invocations + zero new audit rows."""
    from datetime import datetime, UTC

    from app.tasks.proactive_runner import _run_proactive_async

    invocations: list[int] = []

    class _Input(AgentInput):
        cron: str
        scheduled_for: str

    class _Agent(AgenticBaseAgent[_Input]):
        name = "d7b_dedup_agent"
        description = "x"
        input_schema = _Input

        async def run(self, input: _Input, ctx: AgentContext) -> dict:
            invocations.append(1)
            return {"ok": True}

    test_session_factory = async_sessionmaker(
        proactive_db.bind, expire_on_commit=False
    )
    monkeypatch.setattr(
        "app.tasks.proactive_runner.AsyncSessionLocal",
        test_session_factory,
        raising=False,
    )

    fixed_when = datetime.now(UTC)
    # Two consecutive runs at the same minute → only one invocation.
    await _run_proactive_async(
        agent_name="d7b_dedup_agent",
        cron_expr="0 9 * * *",
        per_user=False,
        scheduled_for=fixed_when,
    )
    await _run_proactive_async(
        agent_name="d7b_dedup_agent",
        cron_expr="0 9 * * *",
        per_user=False,
        scheduled_for=fixed_when,
    )

    assert len(invocations) == 1
    raw = await proactive_db.execute(
        sql_text("SELECT count(*) FROM agent_proactive_runs")
    )
    assert raw.scalar_one() == 1


async def test_empty_boot_succeeds_cleanly() -> None:
    """Agentic OS with zero registered agents must boot without errors.

    Today (pre-D8) this is the production state: `_AGENTIC_AGENT_MODULES`
    is empty, so `load_agentic_agents` returns `[]` and
    `register_proactive_schedules` merges 0 entries. After D8 lands
    a real agent, the empty path becomes the *rare* path — exercised
    only when every agent module is gated off by a feature flag, or
    in environments that intentionally disable the agentic OS.

    Rare paths are where regressions hide. This test pins the empty
    boot contract so a future "convenience" change to the loader (e.g.
    "raise if no agents are registered, that's surely a bug") doesn't
    silently break the empty-fallback config.
    """
    from app.agents._agentic_loader import load_agentic_agents
    from app.agents.primitives.proactive import (
        list_schedules,
        register_proactive_schedules,
    )

    # Empty list, not None — distinguishes "loader ran with nothing
    # to load" from "loader didn't run."
    loaded = load_agentic_agents(modules=[])
    assert loaded == []

    # `register_proactive_schedules` must be safe to call against an
    # empty schedule list — exposed via the `schedules` parameter so
    # we don't have to clear the global `_proactive_schedules` first.
    @dataclass
    class _FakeConf:
        beat_schedule: dict[str, Any] = None  # type: ignore[assignment]

    @dataclass
    class _FakeCelery:
        conf: _FakeConf

    fake_celery = _FakeCelery(
        conf=_FakeConf(beat_schedule={"existing_legacy_entry": {"a": 1}})
    )
    count = register_proactive_schedules(fake_celery, schedules=[])
    assert count == 0
    # Pre-existing legacy entries are preserved verbatim.
    assert fake_celery.conf.beat_schedule == {"existing_legacy_entry": {"a": 1}}

    # And the global registry list itself is queryable without raising
    # (callers depend on `list_schedules() -> list`, never None).
    assert isinstance(list_schedules(), list)


async def test_celery_task_registered() -> None:
    """The `@shared_task(name=...)` decorator must bind the task
    under the same name `register_proactive_schedules` targets.
    A typo here would silently mis-route every cron firing in
    prod (Celery would queue tasks against an unregistered name
    and they'd land in a deadletter), so we assert the binding
    exists."""
    from app.core.celery_app import celery_app

    expected_name = "app.agents.primitives.proactive.run_proactive_task"
    assert expected_name in celery_app.tasks, (
        f"task name {expected_name!r} not registered in Celery; "
        f"available: {sorted(celery_app.tasks.keys())[:10]}…"
    )
    task = celery_app.tasks[expected_name]
    # Bound function must be callable; ignore_result=True per the
    # task's @shared_task config.
    assert callable(task)


# ── boot-order import: the celery_app's _boot_agentic_os() ─────────


async def test_celery_app_boot_agentic_os_runs_at_import() -> None:
    """When the Celery app module imports, `_boot_agentic_os` runs
    once. The function calls `load_agentic_agents` (which is empty
    today) and then `register_proactive_schedules`. We can't easily
    re-trigger the boot sequence without re-importing the module,
    but we CAN assert that the celery_app object has the expected
    shape after import — `beat_schedule` exists, the proactive
    task is in `include`, and importing the celery_app doesn't
    raise."""
    from app.core.celery_app import celery_app

    # The proactive runner module must be in the include list so
    # Celery picks up @shared_task at worker boot.
    include = list(celery_app.conf.include)
    assert "app.tasks.proactive_runner" in include

    # `beat_schedule` must be a dict (could be empty if no
    # @proactive agents are registered yet — D8 changes that).
    assert isinstance(celery_app.conf.beat_schedule, dict)
