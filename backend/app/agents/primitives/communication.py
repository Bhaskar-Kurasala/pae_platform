"""Inter-agent communication — Agentic OS Primitive 3.

A single `call_agent()` function that lets one AgenticBaseAgent
invoke another in-process while the runtime tracks the call graph,
detects cycles, enforces a depth ceiling, and writes an audit row
for every link.

The model:

  CallChain  — immutable record threaded through nested calls.
               Carries `root_id` (shared across every link in the
               outermost execute), `parent_id` (the link this call
               descends from), `depth`, the tuple of edges already
               taken (used for cycle detection), and `user_id`.

  call_agent — one entry point. Looks up the callee, validates it
               can be called from `caller_agent`, runs it inside
               `agent_call_timeout_seconds`, writes an
               `agent_call_chain` row regardless of outcome.

Important contract (per-deliverable-4 directive):
  • `root_id` is set on EVERY call, including the first (depth=0).
    Observability tooling can do `WHERE root_id = X` to recover the
    full trace without special-casing single-link traces.

The callee protocol (see `AgenticCallee`) is intentionally minimal
so this primitive doesn't depend on `AgenticBaseAgent` — the actual
class lands in D7. Tests use lightweight mock objects.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives import metrics
from app.core.config import settings
from app.models.agent_call_chain import AgentCallChain


# ── Context var: session bound to the active call_agent boundary ────
#
# Callees implementing the AgenticCallee protocol (e.g.
# AgenticBaseAgent subclasses) need access to the SQLAlchemy session
# that was passed to call_agent at the call site. The protocol's
# `run_agentic(payload, chain)` signature deliberately doesn't carry
# the session — chains are immutable and shareable across threads,
# sessions are not. We bridge via a context var that call_agent
# sets before invoking the callee and resets on the way out.
#
# Why a contextvar and not a kwarg: extending the protocol to
# `run_agentic(payload, chain, session)` would ripple through every
# existing AgenticCallee implementation (D7 base class, future test
# mocks). The contextvar keeps the public protocol stable while
# threading session correctly across async boundaries (asyncio
# context vars propagate across `await`).
_active_session: contextvars.ContextVar[AsyncSession | None] = (
    contextvars.ContextVar("_active_session", default=None)
)


def get_active_session() -> AsyncSession | None:
    """Return the session bound to the active call_agent context, or
    None when no call is in flight. AgenticBaseAgent.run_agentic
    reads this; ad-hoc callees can too."""
    return _active_session.get()

log = structlog.get_logger().bind(layer="communication")


# ── Errors ──────────────────────────────────────────────────────────


class CommunicationError(RuntimeError):
    """Base class for inter-agent call failures.

    All specific errors below carry three attached attributes after
    being raised by `call_agent`:
      • chain_id  — id of the audit row that captured this failure
      • root_id   — the chain's root id
      • depth     — the depth at which the failure occurred

    Callers can read them off the exception without re-querying.
    """


class AgentNotFoundError(CommunicationError):
    """Raised when call_agent's `name` isn't a registered agent."""


class CycleDetectedError(CommunicationError):
    """Raised when a (caller, callee) edge already appears on the chain.

    Cycle detection is on EDGES not NODES so a legitimate diamond
    (A→B and A→C, both reaching D) is allowed; only an actual cycle
    (A→B→A) is rejected. The audit row is still written with
    status='cycle' so the trace is recoverable from the DB.
    """


class CallDepthExceededError(CommunicationError):
    """Raised when chain depth would exceed agent_call_max_depth."""


class AgentPermissionError(CommunicationError):
    """Raised when caller is not in callee's allowed_callers (or
    vice-versa via allowed_callees). Empty allow-lists = no
    restriction; that's the default for agents that haven't opted
    into the access-control surface yet."""


# ── Protocol for the callee ─────────────────────────────────────────


@runtime_checkable
class AgenticCallee(Protocol):
    """Minimal interface a thing must satisfy to be `call_agent`-target.

    AgenticBaseAgent (D7) implements this. Tests use lightweight
    mocks. The callee receives the validated payload (a pydantic
    model or a dict — agents declare the shape per their input
    schema) plus the active CallChain so it can thread the chain
    into any nested call_agent invocations.
    """

    name: str
    allowed_callers: tuple[str, ...]  # empty tuple = any caller permitted
    allowed_callees: tuple[str, ...]  # empty tuple = any callee permitted

    async def run_agentic(
        self,
        payload: dict[str, Any] | BaseModel,
        chain: "CallChain",
    ) -> "AgentCallResult": ...


# ── Registry of agentic agents ──────────────────────────────────────
# We deliberately do NOT reuse the existing `app.agents.registry`
# (BaseAgent registry). The legacy registry stores classes that are
# not AgenticCallee-shaped — calling them via this primitive would
# require an adapter. AgenticBaseAgent (D7) registers here at class
# definition time. Tests register mock objects directly.


_agentic_registry: dict[str, AgenticCallee] = {}


def register_agentic(agent: AgenticCallee) -> AgenticCallee:
    """Register an agentic callee. Idempotent — re-registration with
    the same name replaces the prior entry (matches the legacy
    BaseAgent registry's `@register` semantics)."""
    if not getattr(agent, "name", None):
        raise CommunicationError(
            f"Agentic callee must declare a non-empty .name (got {agent!r})"
        )
    _agentic_registry[agent.name] = agent
    log.info(
        "agentic.registered",
        name=agent.name,
        allowed_callers=list(agent.allowed_callers),
        allowed_callees=list(agent.allowed_callees),
    )
    return agent


def get_agentic(name: str) -> AgenticCallee:
    try:
        return _agentic_registry[name]
    except KeyError as exc:
        available = ", ".join(sorted(_agentic_registry)) or "<none>"
        raise AgentNotFoundError(
            f"Agentic agent {name!r} not registered. Available: {available}"
        ) from exc


def clear_agentic_registry() -> None:
    """Test helper — empties the registry. Production code does not
    call this; the registry is populated once at module import time
    by AgenticBaseAgent's `@register_agentic` decorator (D7)."""
    _agentic_registry.clear()


def list_agentic() -> list[str]:
    return sorted(_agentic_registry)


# ── Result + chain state ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentCallResult:
    """What `call_agent()` returns.

    `output` is the callee's structured response — typically a
    pydantic model. Status `ok` means the call returned cleanly;
    `timeout` / `error` mean we didn't get a usable output and
    `error` carries a human-readable reason.

    `chain_id` is the id of the agent_call_chain row written for
    this call (always present, even when status != ok). `root_id`
    is the chain's root — useful for the caller to thread into a
    follow-up call without creating a new root.

    The "fatal" statuses (`cycle`, `depth_exceeded`, agent-not-found,
    permission-denied) are NOT returned via this dataclass — they
    raise `CommunicationError` subclasses with `chain_id` / `root_id`
    / `depth` attached as attributes. The split is on purpose:
    runtime failures are recoverable in-place; protocol misuses
    should propagate so the caller redesigns its flow.
    """

    callee: str
    output: Any | None
    status: str  # 'ok' | 'error' | 'timeout'
    error: str | None = None
    duration_ms: int = 0
    chain_id: uuid.UUID | None = None
    root_id: uuid.UUID | None = None
    depth: int = 0


@dataclass(frozen=True, slots=True)
class CallChain:
    """Immutable per-call context threaded through nested call_agent
    invocations.

    The factory `start_root(...)` produces the chain for the
    outermost call. Each nested call gets a `descend(...)` copy
    with `parent_id` / `depth` / `edges` updated.

    `edges` is the tuple of (caller, callee) pairs traversed so
    far — cycle detection compares the prospective new edge
    against this set.

    Per-D4 contract: `root_id` is set on every chain instance,
    including the one returned by `start_root` for a single-call
    (depth=0) flow. Observability tools `WHERE root_id = X`
    without special-casing.
    """

    root_id: uuid.UUID
    parent_id: uuid.UUID | None
    caller: str | None
    user_id: uuid.UUID | None
    depth: int
    edges: tuple[tuple[str, str], ...]
    # Cached so we don't re-read settings inside every nested call.
    max_depth: int

    @classmethod
    def start_root(
        cls,
        *,
        caller: str | None = None,
        user_id: uuid.UUID | None = None,
        max_depth: int | None = None,
    ) -> "CallChain":
        """Open a fresh chain for the outermost execute().

        Even for a single-link trace (depth=0, no recursion), the
        root_id we mint here lands in the audit row. `WHERE root_id`
        recovers the trace whether it went one link deep or five.

        `caller` is the name of whatever invoked the root call — for
        an MOA dispatch that's "moa", for a Celery proactive trigger
        that's "proactive:<cron_key>". Pass None when the caller
        identity isn't meaningful (e.g. an internal test harness);
        the audit row records `caller_agent` as NULL in that case.
        """
        return cls(
            root_id=uuid.uuid4(),
            parent_id=None,
            caller=caller,
            user_id=user_id,
            depth=0,
            edges=(),
            max_depth=max_depth or settings.agent_call_max_depth,
        )

    def descend(
        self,
        *,
        new_parent: uuid.UUID,
        new_caller: str,
        new_edge: tuple[str, str],
    ) -> "CallChain":
        """Build the chain a callee will receive.

        `new_parent` is the audit-row id of the call that produced
        the next link (the chain row we just wrote for the current
        call). The next call's row's `parent_id` will point at it.
        """
        return replace(
            self,
            parent_id=new_parent,
            caller=new_caller,
            depth=self.depth + 1,
            edges=self.edges + (new_edge,),
        )


# ── call_agent ──────────────────────────────────────────────────────


async def call_agent(
    name: str,
    payload: dict[str, Any] | BaseModel,
    *,
    session: AsyncSession,
    chain: CallChain,
) -> AgentCallResult:
    """Invoke a registered agentic agent inside the call graph.

    Always writes one `agent_call_chain` row.

    Returns AgentCallResult with status:
      ok       — callee returned cleanly
      error    — callee raised an exception inside `run_agentic`
      timeout  — callee exceeded `agent_call_timeout_seconds`

    Raises CommunicationError subclasses for protocol-level issues:
      CycleDetectedError      — (caller, name) edge already on chain
      CallDepthExceededError  — chain.depth + 1 > chain.max_depth
      AgentNotFoundError      — name not in agentic registry
      AgentPermissionError    — caller / callee allow-list mismatch

    Each raised exception carries `.chain_id`, `.root_id`, `.depth`
    attributes pointing at the audit row that captured the failure.

    The new audit row's id is also returned via the result for
    successful calls, so observability flows have one identifier
    that traces back to the DB regardless of outcome path.
    """
    caller = chain.caller or "<root>"
    new_edge = (caller, name)

    # ── depth ceiling ────────────────────────────────────────────
    next_depth = chain.depth + 1
    if next_depth > chain.max_depth:
        chain_id = await _audit(
            session=session,
            chain=chain,
            callee=name,
            payload=payload,
            status="depth_exceeded",
            error_message=(
                f"depth {next_depth} > max_depth {chain.max_depth}"
            ),
        )
        log.warning(
            "agentic.depth_exceeded",
            caller=caller,
            callee=name,
            depth=next_depth,
            max_depth=chain.max_depth,
            root_id=str(chain.root_id),
        )
        _raise_with_chain(
            CallDepthExceededError(
                f"Call depth would exceed {chain.max_depth} "
                f"(caller={caller!r} → callee={name!r})"
            ),
            chain_id,
            chain.root_id,
            next_depth,
        )

    # ── cycle detection ──────────────────────────────────────────
    if new_edge in chain.edges:
        chain_id = await _audit(
            session=session,
            chain=chain,
            callee=name,
            payload=payload,
            status="cycle",
            error_message=(
                f"edge ({caller}→{name}) already on chain"
            ),
        )
        log.warning(
            "agentic.cycle",
            caller=caller,
            callee=name,
            edges=list(chain.edges),
            root_id=str(chain.root_id),
        )
        _raise_with_chain(
            CycleDetectedError(
                f"Cycle detected: edge ({caller!r} → {name!r}) "
                f"already on chain {[' → '.join(e) for e in chain.edges]}"
            ),
            chain_id,
            chain.root_id,
            next_depth,
        )

    # ── lookup callee ────────────────────────────────────────────
    try:
        callee = get_agentic(name)
    except AgentNotFoundError as exc:
        chain_id = await _audit(
            session=session,
            chain=chain,
            callee=name,
            payload=payload,
            status="error",
            error_message=str(exc),
        )
        _raise_with_chain(exc, chain_id, chain.root_id, next_depth)

    # ── permission check (allowed_callers) ───────────────────────
    if callee.allowed_callers and caller not in callee.allowed_callers:
        chain_id = await _audit(
            session=session,
            chain=chain,
            callee=name,
            payload=payload,
            status="error",
            error_message=(
                f"caller {caller!r} not in {name}.allowed_callers"
            ),
        )
        _raise_with_chain(
            AgentPermissionError(
                f"Agent {name!r} does not permit caller {caller!r}. "
                f"Allowed: {sorted(callee.allowed_callers)}"
            ),
            chain_id,
            chain.root_id,
            next_depth,
        )

    # ── permission check (allowed_callees on caller) ─────────────
    # Only meaningful when the caller is itself a registered
    # agentic agent. Roots and legacy BaseAgent dispatches skip
    # this — they operate from the trust boundary.
    if caller != "<root>":
        try:
            caller_obj = get_agentic(caller)
        except AgentNotFoundError:
            caller_obj = None
        if (
            caller_obj is not None
            and caller_obj.allowed_callees
            and name not in caller_obj.allowed_callees
        ):
            chain_id = await _audit(
                session=session,
                chain=chain,
                callee=name,
                payload=payload,
                status="error",
                error_message=(
                    f"callee {name!r} not in {caller}.allowed_callees"
                ),
            )
            _raise_with_chain(
                AgentPermissionError(
                    f"Agent {caller!r} does not permit calling "
                    f"{name!r}. Allowed: "
                    f"{sorted(caller_obj.allowed_callees)}"
                ),
                chain_id,
                chain.root_id,
                next_depth,
            )

    # ── invoke ───────────────────────────────────────────────────
    # The audit row for the call hasn't been written yet — we mint
    # the chain id eagerly so the callee's nested calls can use it
    # as `parent_id`, and INSERT the row with the final status when
    # the call returns. This avoids the transitional 'queued' state
    # that would violate the migration's CHECK constraint.
    chain_id_for_call = uuid.uuid4()
    next_chain = chain.descend(
        new_parent=chain_id_for_call,
        new_caller=name,
        new_edge=new_edge,
    )

    attempt_start = time.monotonic()
    # Bind the session into the contextvar so the callee's
    # run_agentic implementation (e.g. AgenticBaseAgent) can recover
    # it via `get_active_session()`. Reset is in the finally block
    # at the bottom so every code path restores the prior value —
    # nested call_agent invocations inside the callee see their own
    # session, not ours. asyncio context vars copy on `await` so
    # the callee's reads inside its own coroutine work correctly.
    session_token = _active_session.set(session)
    try:
        result = await asyncio.wait_for(
            callee.run_agentic(payload, next_chain),
            timeout=settings.agent_call_timeout_seconds,
        )
    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - attempt_start) * 1000)
        await _audit(
            session=session,
            chain=chain,
            callee=name,
            payload=payload,
            status="error",
            duration_ms=duration_ms,
            error_message=f"timeout after {settings.agent_call_timeout_seconds}s",
            row_id=chain_id_for_call,
        )
        log.warning(
            "agentic.timeout",
            caller=caller,
            callee=name,
            timeout_seconds=settings.agent_call_timeout_seconds,
            root_id=str(chain.root_id),
        )
        if chain.depth == 0:
            metrics.INTER_AGENT_CALL_DEPTH.observe(next_chain.depth)
        _active_session.reset(session_token)
        return AgentCallResult(
            callee=name,
            output=None,
            status="timeout",
            error=f"timeout after {settings.agent_call_timeout_seconds}s",
            duration_ms=duration_ms,
            chain_id=chain_id_for_call,
            root_id=chain.root_id,
            depth=next_depth,
        )
    except CommunicationError:
        # Errors raised by *nested* call_agent invocations. The
        # inner call already wrote its own audit row. We write
        # ours with status='error' and re-raise; the original
        # exception carries the inner chain_id intact.
        duration_ms = int((time.monotonic() - attempt_start) * 1000)
        await _audit(
            session=session,
            chain=chain,
            callee=name,
            payload=payload,
            status="error",
            duration_ms=duration_ms,
            error_message="nested CommunicationError",
            row_id=chain_id_for_call,
        )
        if chain.depth == 0:
            metrics.INTER_AGENT_CALL_DEPTH.observe(next_chain.depth)
        _active_session.reset(session_token)
        raise
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - attempt_start) * 1000)
        await _audit(
            session=session,
            chain=chain,
            callee=name,
            payload=payload,
            status="error",
            duration_ms=duration_ms,
            error_message=f"{type(exc).__name__}: {exc}",
            row_id=chain_id_for_call,
        )
        log.warning(
            "agentic.error",
            caller=caller,
            callee=name,
            error=str(exc),
            root_id=str(chain.root_id),
        )
        if chain.depth == 0:
            metrics.INTER_AGENT_CALL_DEPTH.observe(next_chain.depth)
        _active_session.reset(session_token)
        return AgentCallResult(
            callee=name,
            output=None,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=duration_ms,
            chain_id=chain_id_for_call,
            root_id=chain.root_id,
            depth=next_depth,
        )

    duration_ms = int((time.monotonic() - attempt_start) * 1000)
    await _audit(
        session=session,
        chain=chain,
        callee=name,
        payload=payload,
        status="ok",
        duration_ms=duration_ms,
        result=_to_jsonable(result.output),
        row_id=chain_id_for_call,
    )
    log.info(
        "agentic.ok",
        caller=caller,
        callee=name,
        depth=next_depth,
        duration_ms=duration_ms,
        root_id=str(chain.root_id),
    )
    if chain.depth == 0:
        metrics.INTER_AGENT_CALL_DEPTH.observe(next_chain.depth)
    _active_session.reset(session_token)
    return AgentCallResult(
        callee=name,
        output=result.output,
        status="ok",
        duration_ms=duration_ms,
        chain_id=chain_id_for_call,
        root_id=chain.root_id,
        depth=next_depth,
    )


# ── helpers ─────────────────────────────────────────────────────────


def _to_jsonable(value: Any) -> dict[str, Any] | None:
    """Coerce arbitrary callee output into JSONB-safe shape."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    # Last-resort string wrap so we never blow up the audit write
    # because a callee returned an exotic object.
    return {"value": repr(value)}


async def _audit(
    *,
    session: AsyncSession,
    chain: CallChain,
    callee: str,
    payload: dict[str, Any] | BaseModel,
    status: str,
    duration_ms: int = 0,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
    row_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert one agent_call_chain row and return its id.

    `row_id` lets the caller pre-mint the id (so a callee's nested
    calls can stash `parent_id` without waiting for the row to land).
    The status passed here MUST be one of the migration-CHECK-allowed
    values: 'ok', 'error', 'cycle', 'depth_exceeded'. There is no
    transient 'queued' state — we insert the row only when the
    final outcome is known.
    """
    assert status in {"ok", "error", "cycle", "depth_exceeded"}, (
        f"unexpected status {status!r}"
    )
    # The agent_call_chain table doesn't have a dedicated error
    # column — the migration kept the schema lean. We stash any
    # error message inside `result` as {"error": "..."} so the
    # audit row carries the diagnosis without a schema bump.
    final_result = result
    if error_message and final_result is None:
        final_result = {"error": error_message}
    elif error_message and isinstance(final_result, dict):
        final_result = {**final_result, "error": error_message}

    row = AgentCallChain(
        id=row_id or uuid.uuid4(),
        root_id=chain.root_id,
        parent_id=chain.parent_id,
        caller_agent=chain.caller,
        callee_agent=callee,
        # Depth in the audit row is the depth of the *callee* link,
        # i.e. one greater than the chain's current depth (which is
        # the caller's depth). For a root call (chain.depth == 0,
        # caller is None), the link's depth is 0 — that's the
        # observability convention: depth=0 means "outermost".
        depth=chain.depth if chain.caller is None else chain.depth + 1,
        payload=_to_jsonable(payload),
        result=final_result,
        status=status,
        user_id=chain.user_id,
        duration_ms=duration_ms or None,
    )
    session.add(row)
    await session.flush()
    return row.id


def _raise_with_chain(
    exc: CommunicationError,
    chain_id: uuid.UUID,
    root_id: uuid.UUID,
    depth: int,
) -> None:
    """Attach trace metadata to the exception and raise.

    Pythonic-y: we can't cleanly attach attributes in a single raise
    expression, so this helper does the binding then raises with
    `from None` to suppress the helper's frame in the traceback.
    """
    setattr(exc, "chain_id", chain_id)
    setattr(exc, "root_id", root_id)
    setattr(exc, "depth", depth)
    raise exc from None


__all__ = [
    "AgentCallResult",
    "AgentNotFoundError",
    "AgentPermissionError",
    "AgenticCallee",
    "CallChain",
    "CallDepthExceededError",
    "CommunicationError",
    "CycleDetectedError",
    "call_agent",
    "clear_agentic_registry",
    "get_agentic",
    "list_agentic",
    "register_agentic",
]
