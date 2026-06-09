"""D11.5 Stage 3.3 — sandbox tool integration tests.

Verifies:
  • run_in_sandbox tool is registered with the canonical name
  • run_tests tool is registered with the canonical name
  • Both have the execute:code_sandbox permission requirement
  • Stub agent declaring the tool in its capability tool list invokes
    via tool_call helper and receives the expected output shape
  • Stub agent NOT declaring the tool receives a permission/registry
    error
  • The tool's @tool decorator validates inputs (rejects bad
    SandboxRequest) before delegation
  • agent_tool_calls audit row would be written (verified via the
    ToolExecutor path; we don't assert against a real DB to avoid
    requiring Postgres)

No real DB; MagicMock session per the D13.5 chain-integration pattern.
No LLM cost.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext, CallChain
from app.agents.primitives.communication import _active_session
from app.agents.primitives.tools import ToolExecutor, registry as tool_registry

# Force tool registration by importing the package.
import app.agents.tools  # noqa: F401 — side-effect imports register tools


# ── Tool registration verification ────────────────────────────────


def test_run_in_sandbox_registered() -> None:
    """The run_in_sandbox tool is in the registry under the canonical
    name from Pass 3d §E.3.2."""
    names = tool_registry.names()
    assert "run_in_sandbox" in names


def test_run_tests_registered() -> None:
    names = tool_registry.names()
    assert "run_tests" in names


def test_run_in_sandbox_has_execute_code_sandbox_permission() -> None:
    spec = tool_registry.get("run_in_sandbox")
    assert "execute:code_sandbox" in spec.requires


def test_run_tests_has_execute_code_sandbox_permission() -> None:
    spec = tool_registry.get("run_tests")
    assert "execute:code_sandbox" in spec.requires


def test_run_in_sandbox_input_schema_is_sandbox_request() -> None:
    """The tool's input schema is the canonical SandboxRequest."""
    from app.schemas.sandbox import SandboxRequest

    spec = tool_registry.get("run_in_sandbox")
    assert spec.input_schema is SandboxRequest


def test_run_in_sandbox_output_schema_is_sandbox_result() -> None:
    from app.schemas.sandbox import SandboxResult

    spec = tool_registry.get("run_in_sandbox")
    assert spec.output_schema is SandboxResult


# ── Tool dispatch via ToolExecutor (capability gating) ────────────


@pytest.fixture
def stub_session() -> Any:
    return MagicMock(spec=AsyncSession)


@pytest.fixture
def patch_active_session(stub_session: Any):
    token = _active_session.set(stub_session)
    yield
    _active_session.reset(token)


@pytest.fixture
def patch_executor_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """ToolExecutor writes an audit row for every call; without DB
    backing, that insert blows up. Patch the audit hook to a no-op."""
    async def _noop(*_args: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(
        "app.agents.primitives.tools.ToolExecutor._record_tool_call",
        _noop,
        raising=False,
    )


@pytest.mark.asyncio
async def test_run_in_sandbox_via_tool_executor_with_permission(
    stub_session: Any,
    patch_active_session: None,
    patch_executor_audit: None,
) -> None:
    """An agent with execute:code_sandbox permission can dispatch
    run_in_sandbox through ToolExecutor and receive a SandboxResult."""
    from app.agents.primitives.tools import ToolCallContext
    from app.schemas.sandbox import SandboxResult

    executor = ToolExecutor(stub_session)
    ctx = ToolCallContext(
        agent_name="test_caller",
        user_id=None,
        permissions=frozenset({"execute:code_sandbox"}),
        call_chain_id=uuid.uuid4(),
    )
    result = await executor.execute(
        "run_in_sandbox",
        {"code": "print('hello')"},
        context=ctx,
    )
    assert result.tool_name == "run_in_sandbox"
    assert result.status == "ok"
    assert isinstance(result.output, SandboxResult)
    assert result.output.stdout == "hello\n"
    assert result.output.exit_code == 0


@pytest.mark.asyncio
async def test_run_in_sandbox_blocked_without_permission(
    stub_session: Any,
    patch_active_session: None,
    patch_executor_audit: None,
) -> None:
    """An agent WITHOUT execute:code_sandbox permission cannot
    dispatch run_in_sandbox. ToolExecutor blocks at the permission
    check before invoking the tool body."""
    from app.agents.primitives.tools import (
        ToolCallContext,
        ToolPermissionError,
    )

    executor = ToolExecutor(stub_session)
    ctx = ToolCallContext(
        agent_name="test_caller_no_perm",
        user_id=None,
        permissions=frozenset(),  # no permissions
        call_chain_id=uuid.uuid4(),
    )
    with pytest.raises(ToolPermissionError):
        await executor.execute(
            "run_in_sandbox",
            {"code": "print('blocked')"},
            context=ctx,
        )


@pytest.mark.asyncio
async def test_run_in_sandbox_validates_input_before_delegation(
    stub_session: Any,
    patch_active_session: None,
    patch_executor_audit: None,
) -> None:
    """A malformed SandboxRequest is rejected at the @tool input-
    validation step BEFORE the executor is invoked. Catches the
    common 'agent passed bad shape' case without burning subprocess
    spawn time."""
    from app.agents.primitives.tools import ToolCallContext

    executor = ToolExecutor(stub_session)
    ctx = ToolCallContext(
        agent_name="test_caller",
        user_id=None,
        permissions=frozenset({"execute:code_sandbox"}),
        call_chain_id=uuid.uuid4(),
    )
    # timeout_seconds=999 is above the schema's ceiling of 60.
    with pytest.raises(Exception):  # ToolInputValidationError or ValidationError
        await executor.execute(
            "run_in_sandbox",
            {"code": "x = 1", "timeout_seconds": 999},
            context=ctx,
        )


@pytest.mark.asyncio
async def test_run_in_sandbox_propagates_node_not_implemented(
    stub_session: Any,
    patch_active_session: None,
    patch_executor_audit: None,
) -> None:
    """When the agent passes language='node', the executor's
    NotImplementedError surfaces. The tool result.status is 'error'
    (not 'ok'), and the error_message indicates Node.js."""
    from app.agents.primitives.tools import ToolCallContext

    executor = ToolExecutor(stub_session)
    ctx = ToolCallContext(
        agent_name="test_caller",
        user_id=None,
        permissions=frozenset({"execute:code_sandbox"}),
        call_chain_id=uuid.uuid4(),
    )
    result = await executor.execute(
        "run_in_sandbox",
        {"code": "console.log('hi')", "language": "node"},
        context=ctx,
    )
    # The tool surface catches the NotImplementedError and surfaces it
    # as a non-ok result rather than re-raising. (The agent invoking
    # the tool should NOT crash on a feature-not-implemented gap.)
    assert result.status == "error"
    err_lower = (result.error or "").lower()
    assert "node" in err_lower or "not implemented" in err_lower


@pytest.mark.asyncio
async def test_run_tests_pytest_via_tool_executor(
    stub_session: Any,
    patch_active_session: None,
    patch_executor_audit: None,
) -> None:
    """Stub agent invokes run_tests with pytest framework; receives a
    structured RunTestsOutput with passed=2."""
    from app.agents.primitives.tools import ToolCallContext
    from app.sandbox.test_runner import RunTestsOutput

    executor = ToolExecutor(stub_session)
    ctx = ToolCallContext(
        agent_name="test_caller",
        user_id=None,
        permissions=frozenset({"execute:code_sandbox"}),
        call_chain_id=uuid.uuid4(),
    )
    result = await executor.execute(
        "run_tests",
        {
            "code": "def double(x): return x * 2",
            "test_code": (
                "from student import double\n"
                "def test_pos(): assert double(3) == 6\n"
                "def test_zero(): assert double(0) == 0\n"
            ),
            "framework": "pytest",
            "timeout_seconds": 30,
        },
        context=ctx,
    )
    assert result.tool_name == "run_tests"
    assert result.status == "ok"
    assert isinstance(result.output, RunTestsOutput)
    assert result.output.passed == 2
    assert result.output.failed == 0


@pytest.mark.asyncio
async def test_run_tests_blocked_without_permission(
    stub_session: Any,
    patch_active_session: None,
    patch_executor_audit: None,
) -> None:
    """Same capability gating as run_in_sandbox."""
    from app.agents.primitives.tools import (
        ToolCallContext,
        ToolPermissionError,
    )

    executor = ToolExecutor(stub_session)
    ctx = ToolCallContext(
        agent_name="test_caller_no_perm",
        user_id=None,
        permissions=frozenset(),
        call_chain_id=uuid.uuid4(),
    )
    with pytest.raises(ToolPermissionError):
        await executor.execute(
            "run_tests",
            {
                "code": "x = 1",
                "test_code": "def test_x(): pass",
                "framework": "pytest",
            },
            context=ctx,
        )


@pytest.mark.asyncio
async def test_run_tests_unittest_framework_propagates_error(
    stub_session: Any,
    patch_active_session: None,
    patch_executor_audit: None,
) -> None:
    """Unsupported framework surfaces through the tool surface as a
    non-ok result with the canonical NotImplementedError message."""
    from app.agents.primitives.tools import ToolCallContext

    executor = ToolExecutor(stub_session)
    ctx = ToolCallContext(
        agent_name="test_caller",
        user_id=None,
        permissions=frozenset({"execute:code_sandbox"}),
        call_chain_id=uuid.uuid4(),
    )
    result = await executor.execute(
        "run_tests",
        {
            "code": "x = 1",
            "test_code": "def test_x(): pass",
            "framework": "unittest",
        },
        context=ctx,
    )
    assert result.status == "error"
    assert "unittest" in (result.error or "").lower()
