"""Tool registry & execution — Agentic OS Primitive 2.

Three concepts that compose:

  ToolSpec     — the immutable record of a registered tool. Carries
                 pydantic schemas for input + output, a cost
                 estimate, and a list of permission strings the
                 caller must hold.

  @tool        — decorator that turns a plain async function into a
                 ToolSpec and adds it to the global registry. The
                 wrapped function still works as a normal callable
                 (so authors can unit-test without going through the
                 executor) but every production call site goes
                 through ToolExecutor.execute().

  ToolExecutor — runs a tool by name. Validates args against the
                 declared input schema, runs the body with a
                 timeout, retries on transient failures, and writes
                 an `agent_tool_calls` audit row regardless of
                 outcome (ok / error / timeout).

The registry is process-local. Every Celery worker / FastAPI worker
auto-discovers tools at import time by importing `app.agents.tools`
which itself imports each stub module — same pattern the agent
registry already uses (see `app.agents.registry._ensure_registered`).

Schemas are the contract; bodies are negotiable. A stub that raises
NotImplementedError is still a "real" tool from the registry's
perspective: callers can introspect its name, description, and
schemas exactly as they would for a fully-implemented tool. The
implementation lands later without breaking any caller code.

Backward compatibility:
  • Existing agents using langchain_core.tools.@tool keep working.
    Those tools are NOT registered here — they are LangChain tools
    invoked directly inside `BaseAgent.execute()`. The new registry
    is for tools that AgenticBaseAgent will call through the
    executor; agents can opt into either pattern (or both) per
    deliverable 7.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import metrics
from app.models.agent_tool_call import AgentToolCall

log = structlog.get_logger().bind(layer="tools")


# ── Errors ──────────────────────────────────────────────────────────


class ToolError(RuntimeError):
    """Base class for tool-layer failures.

    Distinct from arbitrary RuntimeError so callers can decide
    whether to surface the message to a student or eat it silently.
    """


class ToolNotFoundError(ToolError):
    """Raised when ToolExecutor is asked for a tool name not in the registry."""


class ToolValidationError(ToolError):
    """Raised when input args fail the tool's declared input schema."""


class ToolPermissionError(ToolError):
    """Raised when the caller does not hold a required permission."""


class ToolTimeoutError(ToolError):
    """Raised when the tool body exceeds its declared timeout."""


class DuplicateToolError(ToolError):
    """Raised when @tool tries to register a name already in the registry."""


# ── Schemas + spec ──────────────────────────────────────────────────


_InModel = TypeVar("_InModel", bound=BaseModel)
_OutModel = TypeVar("_OutModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolSpec(Generic[_InModel, _OutModel]):
    """Immutable record describing one registered tool.

    Stored by the global ToolRegistry. The `func` is the wrapped
    callable; the executor calls it after validating args against
    `input_schema`. `output_schema` is enforced after the call so a
    misbehaving body that returns the wrong shape is caught at the
    boundary instead of corrupting the audit log.
    """

    name: str
    description: str
    input_schema: type[_InModel]
    output_schema: type[_OutModel]
    func: Callable[..., Awaitable[Any]]
    requires: tuple[str, ...] = field(default_factory=tuple)
    cost_estimate: float = 0.0  # in tokens, dollars, or whatever the author cares about
    timeout_seconds: float = 30.0
    is_stub: bool = False

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<ToolSpec name={self.name!r} stub={self.is_stub}>"


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    """Per-call context the executor threads through.

    `agent_name` and `user_id` flow into the audit row so we can
    answer "what did this agent do for this student in the last
    hour?" without joining four tables.

    `permissions` is the set of perm strings the caller is willing
    to vouch for. The executor checks every entry of `tool.requires`
    against this set before dispatching.

    `call_chain_id` ties tool calls back to the outermost
    AgenticBaseAgent.execute() invocation so a single root id joins
    tool calls + inter-agent links + evaluations.
    """

    agent_name: str
    user_id: uuid.UUID | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    call_chain_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """What ToolExecutor.execute() returns to its caller.

    `output` is the validated pydantic model instance (typed by the
    tool's `output_schema`) so downstream code gets static typing and
    pydantic enforcement, not a raw dict.
    """

    tool_name: str
    output: BaseModel | None
    status: str  # "ok" | "error" | "timeout"
    error: str | None = None
    duration_ms: int = 0
    audit_id: uuid.UUID | None = None


# ── Registry ────────────────────────────────────────────────────────


class ToolRegistry:
    """Process-local registry. Singleton via module-level `registry`.

    Why a singleton instead of a global dict: the class scope lets
    us add helpers (list, search by perm, list by stub status) and
    swap the backing store later without changing call sites. The
    @tool decorator and ToolExecutor both go through this object.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec[Any, Any]] = {}

    def register(self, spec: ToolSpec[Any, Any]) -> None:
        if spec.name in self._tools:
            raise DuplicateToolError(
                f"Tool {spec.name!r} is already registered. "
                "Each name may register exactly once per process."
            )
        self._tools[spec.name] = spec
        log.info(
            "tool.registered",
            name=spec.name,
            is_stub=spec.is_stub,
            requires=list(spec.requires),
            cost_estimate=spec.cost_estimate,
        )

    def get(self, name: str) -> ToolSpec[Any, Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._tools)) or "<none>"
            raise ToolNotFoundError(
                f"Tool {name!r} not registered. Available: {available}"
            ) from exc

    def all(self) -> list[ToolSpec[Any, Any]]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def clear(self) -> None:
        """Reset registry — tests use this between runs."""
        self._tools.clear()


# Module-level singleton. Imported anywhere a caller needs to look
# up or register a tool. Tests can `registry.clear()` at setup.
registry = ToolRegistry()


# ── @tool decorator ─────────────────────────────────────────────────


def tool(
    *,
    name: str,
    description: str,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel],
    requires: Iterable[str] = (),
    cost_estimate: float = 0.0,
    timeout_seconds: float = 30.0,
    is_stub: bool = False,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorate an async function to register it as a tool.

    Usage:

        class SearchInput(BaseModel):
            query: str

        class SearchOutput(BaseModel):
            hits: list[str]

        @tool(
            name="search_course_content",
            description="Hybrid search over course content (RAG).",
            input_schema=SearchInput,
            output_schema=SearchOutput,
            requires=("read:course_content",),
            cost_estimate=0.005,
        )
        async def search_course_content(args: SearchInput) -> SearchOutput:
            return SearchOutput(hits=["..."])

    The decorator is opinionated about the body's signature: tools
    take exactly one argument — a validated input-schema instance.
    No *args / **kwargs sprawl. This makes the call site at the
    executor stable (`await spec.func(validated)`) and the surface
    auto-documenting from the schema.
    """

    def decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"@tool requires an async function; {func.__qualname__} is sync."
            )
        spec = ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            func=func,
            requires=tuple(requires),
            cost_estimate=cost_estimate,
            timeout_seconds=timeout_seconds,
            is_stub=is_stub,
        )
        registry.register(spec)
        # Stash the spec on the function so `func.spec` works when
        # callers want introspection without going through the
        # registry (cheap escape hatch for tests).
        setattr(func, "spec", spec)
        return func

    return decorator


# ── Executor ────────────────────────────────────────────────────────


# Permanent failures are *not* retried — surfacing them quickly is
# more useful than burning a retry budget on something that will
# never succeed.
#
# Per-type rationale (read before adding or removing entries):
#
#   ToolValidationError    Args failed the input schema. A retry
#                          will fail identically because we hand the
#                          same already-failed args back. Surface
#                          status="error" once.
#
#   ToolPermissionError    Caller is missing a required permission.
#                          Permissions are static within a request,
#                          so the second attempt fails the same
#                          guard. Loud-and-fast is better than
#                          three identical denials in the audit log.
#
#   ToolNotFoundError      Looked up an unregistered name. Retrying
#                          accomplishes nothing — the registry is
#                          process-local and won't grow during a
#                          single execute().
#
#   NotImplementedError    A stub fired. Real impl hasn't landed
#                          yet. Retry is wasted; surface so callers
#                          can fall back. NOTE: when stubs become
#                          real (see D7+), this entry stays useful —
#                          a tool that genuinely needs to signal
#                          "not supported here" should still raise
#                          NotImplementedError and not be retried.
#
#   asyncio.CancelledError Caller cancelled the surrounding task
#                          (e.g. request abort, timeout up the
#                          stack). Retrying inside cancelled
#                          context is a contract violation — the
#                          executor must propagate the cancel
#                          signal up promptly.
#
# Anything NOT in this set is treated as transient and retried up
# to `max_retries` times with linear backoff. Add a new entry here
# only after writing the rationale line for it.
_PERMANENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ToolValidationError,
    ToolPermissionError,
    ToolNotFoundError,
    NotImplementedError,
    asyncio.CancelledError,
)


class ToolExecutor:
    """Runs a registered tool with validation, retries, and audit.

    Construct one per session. The session is the AsyncSession the
    caller manages — we never commit it ourselves.

    Why per-session: each tool call writes one `agent_tool_calls`
    row, which we want to participate in the caller's transaction so
    a downstream failure rolls the audit row back too. Audit-only
    use cases that want an isolated commit pass `commit_audit=True`.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._session = session
        self._max_retries = max(0, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._log = log

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any] | BaseModel,
        context: ToolCallContext,
        *,
        commit_audit: bool = False,
    ) -> ToolCallResult:
        """Execute a registered tool by name.

        Returns a ToolCallResult — never raises for tool-internal
        failures (those become status="error" with `error` populated
        so the caller can decide what to surface). Raises
        ToolNotFoundError / ToolValidationError / ToolPermissionError
        only for caller-side bugs.
        """
        spec = registry.get(tool_name)

        # Permission check before we waste cycles on validation.
        missing = [p for p in spec.requires if p not in context.permissions]
        if missing:
            raise ToolPermissionError(
                f"Tool {tool_name!r} requires permission(s) {missing}; "
                f"caller has {sorted(context.permissions)}."
            )

        # Validate (or re-validate) input args.
        try:
            if isinstance(args, BaseModel):
                if not isinstance(args, spec.input_schema):
                    # Caller passed a model of the wrong type. Convert
                    # via dump → re-parse so we get a uniform error
                    # path.
                    validated = spec.input_schema.model_validate(args.model_dump())
                else:
                    validated = args
            else:
                validated = spec.input_schema.model_validate(args)
        except ValidationError as exc:
            raise ToolValidationError(
                f"Tool {tool_name!r} args failed input schema: {exc.errors()}"
            ) from exc

        attempts = 0
        last_exc: BaseException | None = None
        start_total = time.monotonic()

        while True:
            attempts += 1
            attempt_start = time.monotonic()
            try:
                output = await asyncio.wait_for(
                    spec.func(validated),
                    timeout=spec.timeout_seconds,
                )
                duration_ms = int((time.monotonic() - attempt_start) * 1000)
                # Validate the output against the declared schema. A
                # mis-shaped return is a tool bug we want to flag
                # loudly, not silently log.
                if not isinstance(output, spec.output_schema):
                    try:
                        output = spec.output_schema.model_validate(
                            output.model_dump() if isinstance(output, BaseModel) else output
                        )
                    except (AttributeError, ValidationError) as exc:
                        raise ToolError(
                            f"Tool {tool_name!r} returned a value that failed its output schema: {exc}"
                        ) from exc

                audit_id = await self._write_audit(
                    spec=spec,
                    args_payload=_to_dict(validated),
                    result_payload=_to_dict(output),
                    status="ok",
                    error_message=None,
                    duration_ms=duration_ms,
                    context=context,
                    commit=commit_audit,
                )
                metrics.TOOL_CALL_DURATION_MS.labels(
                    tool=spec.name, status="ok"
                ).observe(duration_ms)
                self._log.info(
                    "tool.ok",
                    name=spec.name,
                    duration_ms=duration_ms,
                    attempts=attempts,
                    user_id=str(context.user_id) if context.user_id else None,
                    agent=context.agent_name,
                )
                return ToolCallResult(
                    tool_name=spec.name,
                    output=output,
                    status="ok",
                    duration_ms=duration_ms,
                    audit_id=audit_id,
                )

            except asyncio.TimeoutError as exc:
                last_exc = exc
                duration_ms = int((time.monotonic() - attempt_start) * 1000)
                if attempts > self._max_retries:
                    audit_id = await self._write_audit(
                        spec=spec,
                        args_payload=_to_dict(validated),
                        result_payload=None,
                        status="timeout",
                        error_message=f"timeout after {spec.timeout_seconds}s",
                        duration_ms=duration_ms,
                        context=context,
                        commit=commit_audit,
                    )
                    metrics.TOOL_CALL_DURATION_MS.labels(
                        tool=spec.name, status="timeout"
                    ).observe(duration_ms)
                    self._log.warning(
                        "tool.timeout",
                        name=spec.name,
                        timeout=spec.timeout_seconds,
                        attempts=attempts,
                    )
                    return ToolCallResult(
                        tool_name=spec.name,
                        output=None,
                        status="timeout",
                        error=f"timeout after {spec.timeout_seconds}s",
                        duration_ms=duration_ms,
                        audit_id=audit_id,
                    )
                # Else: brief backoff and retry.
                await asyncio.sleep(self._retry_backoff * attempts)
                continue

            except _PERMANENT_EXCEPTIONS as exc:
                last_exc = exc
                duration_ms = int((time.monotonic() - attempt_start) * 1000)
                audit_id = await self._write_audit(
                    spec=spec,
                    args_payload=_to_dict(validated),
                    result_payload=None,
                    status="error",
                    error_message=f"{type(exc).__name__}: {exc}",
                    duration_ms=duration_ms,
                    context=context,
                    commit=commit_audit,
                )
                metrics.TOOL_CALL_DURATION_MS.labels(
                    tool=spec.name, status="error"
                ).observe(duration_ms)
                self._log.warning(
                    "tool.permanent_error",
                    name=spec.name,
                    error=str(exc),
                    attempts=attempts,
                )
                return ToolCallResult(
                    tool_name=spec.name,
                    output=None,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=duration_ms,
                    audit_id=audit_id,
                )

            except Exception as exc:  # noqa: BLE001 - retry-on-anything bucket
                last_exc = exc
                duration_ms = int((time.monotonic() - attempt_start) * 1000)
                if attempts > self._max_retries:
                    audit_id = await self._write_audit(
                        spec=spec,
                        args_payload=_to_dict(validated),
                        result_payload=None,
                        status="error",
                        error_message=f"{type(exc).__name__}: {exc}",
                        duration_ms=duration_ms,
                        context=context,
                        commit=commit_audit,
                    )
                    metrics.TOOL_CALL_DURATION_MS.labels(
                        tool=spec.name, status="error"
                    ).observe(duration_ms)
                    self._log.warning(
                        "tool.error_after_retries",
                        name=spec.name,
                        error=str(exc),
                        attempts=attempts,
                    )
                    return ToolCallResult(
                        tool_name=spec.name,
                        output=None,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                        duration_ms=duration_ms,
                        audit_id=audit_id,
                    )
                await asyncio.sleep(self._retry_backoff * attempts)

        # Unreachable; while True only exits via return.
        raise AssertionError(f"unreachable: {last_exc!r}")

    async def _write_audit(
        self,
        *,
        spec: ToolSpec[Any, Any],
        args_payload: dict[str, Any],
        result_payload: dict[str, Any] | None,
        status: str,
        error_message: str | None,
        duration_ms: int,
        context: ToolCallContext,
        commit: bool,
    ) -> uuid.UUID:
        row = AgentToolCall(
            agent_name=context.agent_name,
            tool_name=spec.name,
            args=args_payload,
            result=result_payload,
            status=status,
            error_message=error_message,
            duration_ms=duration_ms,
            user_id=context.user_id,
            call_chain_id=context.call_chain_id,
        )
        self._session.add(row)
        await self._session.flush()
        if commit:
            await self._session.commit()
        return row.id


def _to_dict(model: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
    """Serialize for JSONB storage. Pydantic models → mode='json' so
    UUIDs / datetimes / decimals round-trip cleanly."""
    if model is None:
        return {}
    if isinstance(model, BaseModel):
        return model.model_dump(mode="json")
    return dict(model)


# ── auto-discovery ──────────────────────────────────────────────────


_DISCOVERED = False


def ensure_tools_loaded() -> None:
    """Idempotent import of the tools package so all stubs register.

    Mirrors the agent registry's `_ensure_registered()` pattern.
    Tests that want a clean registry call `registry.clear()` first
    and then call this to re-import; module-level imports are
    side-effecting (each tool calls @tool at import time).

    Emits a single `tool_registry.loaded` log line on first load
    with a stubs/real breakdown — that line acts as a free progress
    bar as we replace stubs with real implementations across the
    quarter. `grep tool_registry.loaded` in prod logs to read it.
    """
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True
    # Importing the package triggers __init__.py which imports each
    # tool module. The decorators run on import, populating registry.
    import app.agents.tools  # noqa: F401

    specs = registry.all()
    total = len(specs)
    stubs = sum(1 for s in specs if s.is_stub)
    real = total - stubs
    log.info(
        "tool_registry.loaded",
        total=total,
        stubs=stubs,
        real=real,
        # Names list is bounded (~11 today, capped by registry size),
        # so it's safe to surface in the structured log. Useful when
        # diffing prod vs dev to confirm an env has the tools you
        # expect.
        names=sorted(s.name for s in specs),
    )


__all__ = [
    "DuplicateToolError",
    "ToolCallContext",
    "ToolCallResult",
    "ToolError",
    "ToolExecutor",
    "ToolNotFoundError",
    "ToolPermissionError",
    "ToolRegistry",
    "ToolSpec",
    "ToolTimeoutError",
    "ToolValidationError",
    "ensure_tools_loaded",
    "registry",
    "tool",
]
