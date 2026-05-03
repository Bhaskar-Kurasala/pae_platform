"""ToolRegistry / @tool / ToolExecutor — registration, validation,
retries, timeouts, audit-row writes, and per-stub schema checks.

The 11 production stubs all raise NotImplementedError. We don't test
"the body works" — there's no body. We test that:

  • each stub registered cleanly with its declared schemas
  • the input schema rejects malformed args
  • the executor catches NotImplementedError and writes status='error'
    audit rows so a stub flag in prod doesn't crash the call site
  • round-trip dispatch with an inline test tool works end-to-end:
    register → execute → audit row exists with the right shape

The Postgres fixture from conftest is reused for the audit-table
tests. Pure-validation tests don't need a DB.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import (
    DuplicateToolError,
    ToolCallContext,
    ToolExecutor,
    ToolNotFoundError,
    ToolPermissionError,
    ToolValidationError,
    ensure_tools_loaded,
    tool,
    tool_registry,
)
from app.agents.primitives.tools import _to_dict


pytestmark = pytest.mark.asyncio


# ── Fixture: clean registry per test ────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_registry() -> AsyncGenerator[None, None]:
    """Each test runs against a freshly populated registry.

    Cycle per test:
      • clear()                       (start clean)
      • reload tools modules          (re-runs @tool decorators)
      • yield                         (test body)
      • clear() + reload again        (so the next test starts clean)

    Why reload at SETUP (not teardown):
      The first version of this fixture cleared at setup and reloaded
      at teardown — so the test body ran against an empty registry,
      and the stub-loaded tests failed because `ensure_tools_loaded()`
      is a cached no-op (Python's import cache means the second
      `import app.agents.tools` returns the already-loaded module
      without re-running its body). We have to actively
      `importlib.reload` to re-fire the @tool decorators after a
      `registry.clear()`. Doing it at SETUP gives the test body a
      live, populated registry the way production sees it.

      This is the canonical pytest "import-cache makes my reset a
      no-op" trap — easy to recreate in the next D-N's fixture if
      you don't internalise the rule. Reload sites that side-effect
      always reload at setup, never at teardown.

    Tests that want a totally empty registry can call
    `tool_registry.clear()` inside the test body — no fixture
    coordination needed. The loaded stubs being present is the
    common case.
    """
    import importlib

    import app.agents.tools as tools_pkg
    import app.agents.tools.career_tools as career_tools
    import app.agents.tools.code_tools as code_tools
    import app.agents.tools.content_tools as content_tools
    import app.agents.tools.github_tools as github_tools
    import app.agents.tools.student_tools as student_tools

    # D10: memory_tools (which contained the retired D3 stubs
    # recall_memory + store_memory) is NO LONGER reloaded here. Its
    # stubs were superseded by the universal tools at
    # app/agents/tools/universal/. Reloading memory_tools would
    # re-register the stubs and mask the retirement.
    #
    # D10: universal tools are NOT reloaded explicitly either.
    # importlib.reload on a sub-tool module reinstantiates its pydantic
    # model classes, which breaks `isinstance` checks in tests that
    # imported those classes at module-load time. The package reload
    # below re-executes `from app.agents.tools import universal`, which
    # imports the EXISTING universal module from sys.modules without
    # re-executing it — so the universal tools' @tool decorators don't
    # re-fire and their model classes stay stable. This is sufficient
    # for the test_tools fixture's purpose (re-populating the D3 stub
    # roster); tests that exercise universal tools live in their own
    # subdirectory and don't need this fixture's reset cycle.

    def _reload_all() -> None:
        tool_registry.clear()
        # Reset the discovery sentinel so ensure_tools_loaded() runs
        # again if the test calls it.
        import app.agents.primitives.tools as tools_mod

        tools_mod._DISCOVERED = False
        for mod in (
            student_tools,
            content_tools,
            code_tools,
            github_tools,
            career_tools,
            tools_pkg,
        ):
            importlib.reload(mod)

    _reload_all()
    yield
    _reload_all()


# ── Inline test fixtures (tools we register on-demand inside tests) ─


class _InlineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=0)
    note: str = Field(default="", max_length=200)


class _InlineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doubled: int


def _register_doubler() -> None:
    """Registers a `_test_doubler` tool. Tests that use this should
    not also rely on the production stubs — call
    `tool_registry.clear()` first if you want an isolated registry."""

    @tool(
        name="_test_doubler",
        description="Doubles n.",
        input_schema=_InlineIn,
        output_schema=_InlineOut,
        requires=(),
        cost_estimate=0.0,
        timeout_seconds=2.0,
    )
    async def _doubler(args: _InlineIn) -> _InlineOut:  # pragma: no cover
        return _InlineOut(doubled=args.n * 2)


# ── Registry guards ─────────────────────────────────────────────────


async def test_duplicate_registration_raises() -> None:
    _register_doubler()
    with pytest.raises(DuplicateToolError, match="_test_doubler"):
        _register_doubler()


async def test_unknown_tool_raises_not_found() -> None:
    with pytest.raises(ToolNotFoundError, match="missing_tool"):
        tool_registry.get("missing_tool")


async def test_sync_function_rejected() -> None:
    """Tools must be async — we don't want to run blocking IO inline
    on the event loop."""
    with pytest.raises(TypeError, match="async function"):
        @tool(  # noqa: B015 - intentional decorator-with-side-effect
            name="_test_sync",
            description="x",
            input_schema=_InlineIn,
            output_schema=_InlineOut,
        )
        def _sync(args: _InlineIn) -> _InlineOut:  # noqa: ARG001
            return _InlineOut(doubled=0)


# ── Input validation ────────────────────────────────────────────────


async def test_executor_validates_args(pg_session: AsyncSession) -> None:
    _register_doubler()
    executor = ToolExecutor(pg_session)
    with pytest.raises(ToolValidationError):
        await executor.execute(
            "_test_doubler",
            args={"n": -1},  # ge=0 violated
            context=ToolCallContext(agent_name="test_agent"),
        )


async def test_executor_unknown_tool_raises(pg_session: AsyncSession) -> None:
    executor = ToolExecutor(pg_session)
    with pytest.raises(ToolNotFoundError):
        await executor.execute(
            "ghost_tool",
            args={},
            context=ToolCallContext(agent_name="test_agent"),
        )


async def test_executor_enforces_permissions(pg_session: AsyncSession) -> None:
    @tool(
        name="_test_perm",
        description="needs perm",
        input_schema=_InlineIn,
        output_schema=_InlineOut,
        requires=("read:secret",),
    )
    async def _needs_perm(args: _InlineIn) -> _InlineOut:  # pragma: no cover
        return _InlineOut(doubled=args.n * 2)

    executor = ToolExecutor(pg_session)
    with pytest.raises(ToolPermissionError, match="read:secret"):
        await executor.execute(
            "_test_perm",
            args={"n": 1},
            context=ToolCallContext(
                agent_name="test_agent",
                permissions=frozenset({"read:other"}),
            ),
        )


# ── Successful round-trip + audit row ───────────────────────────────


async def _audit_count(session: AsyncSession) -> int:
    raw = await session.execute(
        sql_text("SELECT count(*) FROM agent_tool_calls")
    )
    return int(raw.scalar_one())


async def test_executor_round_trip_writes_audit_row(
    pg_session: AsyncSession,
) -> None:
    """Spec asks: register → call through executor → audit log row.

    We need agent_tool_calls in the test schema. The conftest only
    creates agent_memory; this test creates agent_tool_calls
    on-demand for the same throwaway schema.
    """
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args JSONB NOT NULL,
                result JSONB,
                status TEXT NOT NULL,
                error_message TEXT,
                duration_ms INT NOT NULL,
                user_id UUID,
                call_chain_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await pg_session.commit()

    _register_doubler()
    executor = ToolExecutor(pg_session)
    user_id = uuid.uuid4()
    chain_id = uuid.uuid4()

    result = await executor.execute(
        "_test_doubler",
        args={"n": 21, "note": "hi"},
        context=ToolCallContext(
            agent_name="test_agent",
            user_id=user_id,
            call_chain_id=chain_id,
        ),
    )
    assert result.status == "ok"
    assert isinstance(result.output, _InlineOut)
    assert result.output.doubled == 42
    await pg_session.flush()

    raw = await pg_session.execute(
        sql_text(
            "SELECT agent_name, tool_name, status, args, result, "
            "user_id, call_chain_id "
            "FROM agent_tool_calls"
        )
    )
    rows = raw.all()
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == "test_agent"
    assert row[1] == "_test_doubler"
    assert row[2] == "ok"
    assert row[3] == {"n": 21, "note": "hi"}
    assert row[4] == {"doubled": 42}
    assert row[5] == user_id
    assert row[6] == chain_id


# ── Failure paths ───────────────────────────────────────────────────


async def test_executor_audits_timeouts(pg_session: AsyncSession) -> None:
    """Slow tool → executor times out → status='timeout' result, no
    raise. Use a 0.05s timeout against a tool that sleeps 0.5s."""
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args JSONB NOT NULL,
                result JSONB,
                status TEXT NOT NULL,
                error_message TEXT,
                duration_ms INT NOT NULL,
                user_id UUID,
                call_chain_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await pg_session.commit()

    @tool(
        name="_test_slow",
        description="sleeps too long",
        input_schema=_InlineIn,
        output_schema=_InlineOut,
        timeout_seconds=0.05,
    )
    async def _slow(args: _InlineIn) -> _InlineOut:  # noqa: ARG001
        await asyncio.sleep(0.5)
        return _InlineOut(doubled=0)

    executor = ToolExecutor(pg_session, max_retries=0)
    result = await executor.execute(
        "_test_slow",
        args={"n": 1},
        context=ToolCallContext(agent_name="test_agent"),
    )
    assert result.status == "timeout"
    assert "timeout" in (result.error or "").lower()
    raw = await pg_session.execute(
        sql_text("SELECT status FROM agent_tool_calls WHERE tool_name = :t"),
        {"t": "_test_slow"},
    )
    assert raw.scalar_one() == "timeout"


async def test_executor_audits_stub_not_implemented(
    pg_session: AsyncSession,
) -> None:
    """A stub tool returning NotImplementedError must NOT crash the
    executor — we get a status='error' result + audit row. This is
    what protects production from a half-implemented stub."""
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args JSONB NOT NULL,
                result JSONB,
                status TEXT NOT NULL,
                error_message TEXT,
                duration_ms INT NOT NULL,
                user_id UUID,
                call_chain_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await pg_session.commit()

    @tool(
        name="_test_stub",
        description="raises NotImplementedError",
        input_schema=_InlineIn,
        output_schema=_InlineOut,
        is_stub=True,
    )
    async def _stub(args: _InlineIn) -> _InlineOut:  # noqa: ARG001
        raise NotImplementedError("stub")

    executor = ToolExecutor(pg_session, max_retries=0)
    result = await executor.execute(
        "_test_stub",
        args={"n": 1},
        context=ToolCallContext(agent_name="test_agent"),
    )
    assert result.status == "error"
    assert "NotImplementedError" in (result.error or "")


async def test_executor_retries_transient_failures(
    pg_session: AsyncSession,
) -> None:
    """Generic exception → executor retries up to `max_retries` times.
    On final attempt success, status='ok' and the audit row reflects
    only the final attempt (we don't currently audit each attempt)."""
    await pg_session.execute(
        sql_text(
            """
            CREATE TABLE IF NOT EXISTS agent_tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args JSONB NOT NULL,
                result JSONB,
                status TEXT NOT NULL,
                error_message TEXT,
                duration_ms INT NOT NULL,
                user_id UUID,
                call_chain_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await pg_session.commit()

    counter = {"calls": 0}

    @tool(
        name="_test_flaky",
        description="fails twice then succeeds",
        input_schema=_InlineIn,
        output_schema=_InlineOut,
    )
    async def _flaky(args: _InlineIn) -> _InlineOut:
        counter["calls"] += 1
        if counter["calls"] < 3:
            raise RuntimeError("transient")
        return _InlineOut(doubled=args.n * 2)

    executor = ToolExecutor(
        pg_session,
        max_retries=2,
        retry_backoff_seconds=0.0,  # instant retry for the test
    )
    result = await executor.execute(
        "_test_flaky",
        args={"n": 5},
        context=ToolCallContext(agent_name="test_agent"),
    )
    assert result.status == "ok"
    assert counter["calls"] == 3


# ── _to_dict serialization helper ───────────────────────────────────


async def test_to_dict_handles_none() -> None:
    assert _to_dict(None) == {}


async def test_to_dict_handles_pydantic_with_uuid() -> None:
    """UUIDs / datetimes must round-trip cleanly so JSONB writes don't
    blow up with `Object of type UUID is not JSON serializable`."""

    class _M(BaseModel):
        x: uuid.UUID

    out = _to_dict(_M(x=uuid.UUID("11111111-1111-1111-1111-111111111111")))
    assert out == {"x": "11111111-1111-1111-1111-111111111111"}


# ── Per-stub schema contracts ───────────────────────────────────────
# Spec: every stub has a real pydantic schema. Tests verify the input
# validation works on every stub. NO body assertions — bodies are
# NotImplementedError.


async def test_all_stubs_loaded() -> None:
    """Stubs still registered after D10: 4 student + 1 content + 1 code
    + 1 github + 2 career = 9. The D3 memory stubs (recall_memory,
    store_memory) were retired in D10 and replaced by the universal
    tools memory_recall / memory_write at app/agents/tools/universal/.
    See docs/architecture/pass-3d-tool-implementations.md §D."""
    ensure_tools_loaded()
    expected = {
        "get_student_state",
        "update_mastery",
        "send_student_message",
        "schedule_review",
        "search_course_content",
        "run_ruff",
        "read_github_pr",
        "search_jobs",
        "parse_jd",
    }
    have = set(tool_registry.names())
    assert expected.issubset(have)
    # Each stub must declare itself a stub.
    for name in expected:
        spec = tool_registry.get(name)
        assert spec.is_stub is True, f"{name} should be marked is_stub=True"


async def test_d10_retired_d3_memory_stubs() -> None:
    """Pin the D10 retirement so a future revert is loud.

    The D3 stubs `recall_memory` and `store_memory` were superseded by
    the universal tools `memory_recall` and `memory_write` in D10
    (Pass 3d §D, §A.1). The package's import block in
    app/agents/tools/__init__.py no longer imports memory_tools, so
    the stubs do not register at all. Re-introducing them creates
    dead NotImplementedError-raisers competing with the real tools.
    """
    ensure_tools_loaded()
    have = set(tool_registry.names())
    assert "recall_memory" not in have, (
        "D3 stub 'recall_memory' should be retired by D10. The "
        "replacement is 'memory_recall' from app/agents/tools/universal/."
    )
    assert "store_memory" not in have, (
        "D3 stub 'store_memory' should be retired by D10. The "
        "replacement is 'memory_write' from app/agents/tools/universal/."
    )


@pytest.mark.parametrize(
    "tool_name,bad_args",
    [
        # D10: D3 memory stubs (recall_memory, store_memory) retired. Their
        # successors (memory_recall, memory_write) get their own schema-
        # validation tests at tests/test_agents/tools/universal/.
        ("get_student_state", {}),  # missing user_id
        ("get_student_state", {"user_id": "not-a-uuid"}),  # bad UUID
        ("update_mastery", {"user_id": str(uuid.uuid4())}),  # missing skill_id
        (
            "update_mastery",
            {
                "user_id": str(uuid.uuid4()),
                "skill_id": str(uuid.uuid4()),
                "mastery_level": "wizard",  # not in literal
                "source_event": "x",
            },
        ),
        ("send_student_message", {"user_id": str(uuid.uuid4())}),  # missing kind/title/body
        (
            "send_student_message",
            {
                "user_id": str(uuid.uuid4()),
                "kind": "nudge",
                "title": "x",
                "body": "x",
                "cta_url": "y" * 3000,  # > 2000 chars
            },
        ),
        ("schedule_review", {"user_id": str(uuid.uuid4())}),  # missing due_at + reason
        ("search_course_content", {"query": ""}),  # min_length=1
        ("search_course_content", {"query": "ok", "k": 100}),  # k le=20
        ("run_ruff", {"code": ""}),  # min_length=1
        ("read_github_pr", {"owner": "o", "repo": "r"}),  # missing number
        ("read_github_pr", {"owner": "o", "repo": "r", "number": 0}),  # ge=1
        ("search_jobs", {"role_keywords": []}),  # min_length=1
        ("search_jobs", {"role_keywords": ["x"], "k": 999}),  # le=50
        ("parse_jd", {}),  # missing raw_text
        ("parse_jd", {"raw_text": "short"}),  # min_length=10
    ],
)
async def test_stub_schemas_reject_bad_args(
    tool_name: str, bad_args: dict[str, Any]
) -> None:
    """Each stub's input schema must reject malformed args. The test
    parametrises across every shape we care about so a future schema
    relaxation is caught immediately."""
    ensure_tools_loaded()
    spec = tool_registry.get(tool_name)
    with pytest.raises(ValidationError):
        spec.input_schema.model_validate(bad_args)


@pytest.mark.parametrize(
    "tool_name,good_args",
    [
        # D10: D3 memory stubs (recall_memory, store_memory) retired —
        # see test_d10_retired_d3_memory_stubs above.
        ("get_student_state", {"user_id": str(uuid.uuid4())}),
        (
            "update_mastery",
            {
                "user_id": str(uuid.uuid4()),
                "skill_id": str(uuid.uuid4()),
                "mastery_level": "proficient",
                "source_event": "lesson:completed:x",
            },
        ),
        (
            "send_student_message",
            {
                "user_id": str(uuid.uuid4()),
                "kind": "nudge",
                "title": "Quick check-in",
                "body": "Saw you've been quiet — anything blocking?",
            },
        ),
        (
            "schedule_review",
            {
                "user_id": str(uuid.uuid4()),
                "due_at": "2026-06-01T10:00:00+00:00",
                "reason": "mastery dropped to novice",
            },
        ),
        ("search_course_content", {"query": "explain RAG"}),
        ("run_ruff", {"code": "import os\n"}),
        ("read_github_pr", {"owner": "x", "repo": "y", "number": 1}),
        ("search_jobs", {"role_keywords": ["senior genai"]}),
        (
            "parse_jd",
            {"raw_text": "Senior GenAI Engineer — must know LangGraph and RAG."},
        ),
    ],
)
async def test_stub_schemas_accept_minimal_valid_args(
    tool_name: str, good_args: dict[str, Any]
) -> None:
    """Mirror of the rejection table — minimal valid args must parse."""
    ensure_tools_loaded()
    spec = tool_registry.get(tool_name)
    parsed = spec.input_schema.model_validate(good_args)
    assert parsed is not None
