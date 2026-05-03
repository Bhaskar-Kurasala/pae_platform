"""AgenticBaseAgent — the new agent base class.

Composes the five Agentic OS primitives (memory, tools,
inter-agent communication, self-evaluation, proactive triggers)
into a single class that subclasses inherit. Each subclass
implements one method — `run(input, ctx)` — and gets the rest for
free.

Design:

  • This base class is a *composer*, not a *re-implementer*. We
    only call the public surface of each primitive. If a primitive's
    public surface is missing something we need, we add it to the
    primitive — not bypass it from here.

  • Every primitive has a class-level opt-out attribute:
      uses_memory          : bool = True
      uses_tools           : bool = True
      uses_inter_agent     : bool = True
      uses_self_eval       : bool = False   ← off by default
      uses_proactive       : bool = False   ← off by default
    Self-eval defaults off so unit tests don't need a critic LLM
    and dev runs don't double LLM calls. Proactive defaults off
    until the redis-backed escalation limiter ships (see
    docs/followups/escalation-limiter-redis.md). The other three
    are cheap to leave on; opt out only when the agent genuinely
    has no memory needs / no tool calls / etc.

  • execute() returns AgentResult — the same dataclass D5 defined.
    No agent has its own return shape; that's how we avoid 26
    incompatible signatures.

  • execute() takes an AgentInput pydantic model + an AgentContext
    pydantic model. AgentInput is opaque to the base class
    (subclasses define their own); AgentContext carries the
    ambient request state (user, chain, session) that the
    primitives need.

Backward compatibility:
  The legacy `BaseAgent` (LangGraph MOA, 26 existing agents) keeps
  working. AgenticBaseAgent does NOT subclass BaseAgent — they are
  parallel hierarchies that register in different registries. MOA
  dispatches to BaseAgent today; D7b will give MOA a path to
  AgenticBaseAgent.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, ClassVar, Generic, TypeVar

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives.communication import (
    AgentCallResult,
    AgenticCallee,
    CallChain,
    call_agent,
    get_active_session,
    register_agentic,
)
from app.agents.primitives.evaluation import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_THRESHOLD,
    AgentResult,
    Critic,
    EscalationLimiter,
    escalation_limiter,
    evaluate_with_retry,
)
from app.agents.primitives.memory import MemoryRow, MemoryStore, MemoryWrite
from app.agents.primitives.tools import (
    ToolCallContext,
    ToolCallResult,
    ToolExecutor,
)

log = structlog.get_logger().bind(layer="agentic_base")


# ── Public input/output models ──────────────────────────────────────


class AgentInput(BaseModel):
    """Base class for an agent's input payload.

    Each agent subclass overrides this with its own typed fields.
    Keeping `extra='forbid'` so an agent that accidentally receives
    an unexpected key fails loudly rather than smuggling it through.
    """

    model_config = ConfigDict(extra="forbid")


class AgentContext(BaseModel):
    """Ambient state every agent execution needs.

    Carries the user the agent is acting on behalf of, the call
    chain (so nested call_agent invocations propagate root_id),
    the SQLAlchemy session, and the permissions the caller is
    willing to vouch for.

    `arbitrary_types_allowed=True` lets us store the AsyncSession
    instance directly — pydantic doesn't need to validate it, just
    pass it through.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    user_id: uuid.UUID | None = None
    chain: CallChain
    session: AsyncSession
    permissions: frozenset[str] = Field(default_factory=frozenset)
    # Free-form bag the surrounding flow can stash hints into without
    # polluting the typed surface — e.g. proactive trigger source,
    # request id, feature-flag overrides.
    extra: dict[str, Any] = Field(default_factory=dict)


_InputT = TypeVar("_InputT", bound=AgentInput)


# ── Base class ──────────────────────────────────────────────────────


class AgenticBaseAgent(Generic[_InputT]):
    """Base class every new agentic agent inherits from.

    Subclass contract:

        class MyAgent(AgenticBaseAgent[MyInputModel]):
            name: ClassVar[str] = "my_agent"
            description: ClassVar[str] = "Does the thing."
            input_schema: ClassVar[type[AgentInput]] = MyInputModel

            async def run(
                self, input: MyInputModel, ctx: AgentContext
            ) -> Any:
                # Your logic. Return whatever shape you like — the
                # base class wraps it in AgentResult.
                ...

    The class is registered with the agentic registry at
    construction time of its first instance (see
    `__init_subclass__`). That mirrors the legacy `@register`
    decorator pattern but is automatic — subclasses don't need a
    decorator.

    Opt-outs are class-level booleans. An agent that flips
    `uses_self_eval = False` does NOT pay the critic-call cost.
    """

    # ── identity (required) ────────────────────────────────────────

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    input_schema: ClassVar[type[AgentInput]] = AgentInput

    # ── allow-lists (optional, empty = unrestricted) ───────────────

    allowed_callers: ClassVar[tuple[str, ...]] = ()
    allowed_callees: ClassVar[tuple[str, ...]] = ()

    # ── opt-outs ──────────────────────────────────────────────────

    uses_memory: ClassVar[bool] = True
    uses_tools: ClassVar[bool] = True
    uses_inter_agent: ClassVar[bool] = True
    # Self-eval defaults OFF: it doubles LLM calls and adds latency
    # on every execution. Land each new agent dark; flip to True
    # once you have baseline scores you trust.
    uses_self_eval: ClassVar[bool] = False
    # Proactive defaults OFF until the redis-backed escalation
    # limiter ships (see docs/followups/escalation-limiter-redis.md).
    uses_proactive: ClassVar[bool] = False

    # ── self-eval tuning (only consulted when uses_self_eval=True) ─

    eval_threshold: ClassVar[float] = DEFAULT_THRESHOLD
    eval_max_retries: ClassVar[int] = DEFAULT_MAX_RETRIES

    # ── lifecycle ──────────────────────────────────────────────────

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register every concrete subclass.

        Skip the class itself if `name` is empty — that's how we
        let intermediate abstract subclasses exist without binding
        a registry name. (Mirror of the legacy `@register` pattern.)

        Registration is idempotent: re-importing the module replaces
        the existing entry. Tests that need a clean slate call
        `clear_agentic_registry()` from the communication primitive.
        """
        super().__init_subclass__(**kwargs)
        if not cls.name:
            return
        # An instance is what implements the AgenticCallee protocol
        # (.run_agentic is an instance method). Register a singleton.
        instance = cls()
        register_agentic(instance)

    # ── subclass override point ────────────────────────────────────

    async def run(self, input: _InputT, ctx: AgentContext) -> Any:
        """Subclasses override this. Return whatever shape you want;
        the base class wraps the result in AgentResult.

        The default raises so a subclass that forgets to override
        gets a loud failure instead of a silent passthrough."""
        raise NotImplementedError(
            f"{type(self).__name__}.run() must be overridden."
        )

    # ── public dispatcher (the way callers invoke the agent) ──────

    async def execute(
        self,
        input: _InputT | dict[str, Any],
        ctx: AgentContext,
    ) -> AgentResult:
        """Run the agent end-to-end with all primitives composed.

        Sequence:
          1. Validate + coerce `input` against `cls.input_schema`.
          2. (Optional, uses_self_eval) Wrap `run()` in
             evaluate_with_retry. The factory closure regenerates
             the input each attempt so the critic's reasoning can
             be threaded into the next call as `feedback`.
          3. Otherwise, run() once, wrap output in AgentResult.

        Memory, tools, and inter-agent calls are accessed by
        subclasses inside `run()` via `self.memory(ctx)`, `self.tool_call(...)`,
        `self.call(...)`. The base class doesn't drive them — the
        agent author decides which to use, and when. This is
        deliberate: opt-outs would be meaningless if the base class
        were always calling `memory.recall()` whether the agent
        wanted it or not.
        """
        validated: _InputT = self._validate_input(input)
        request_str = self._request_for_eval(validated)

        # ── D9 / Pass 3g §A.5 — input safety scan ──────────────────
        # The gate wraps run(). The orchestrator scans the canonical
        # `user_message` before the Supervisor runs (see
        # agentic_orchestrator.py); that's the OUTER scan. This
        # INNER scan covers specialist invocations from non-orchestrator
        # paths: webhook-triggered agents, cron-triggered agents,
        # admin tools that bypass the orchestrator.
        #
        # The Supervisor itself is exempt from the inner scan
        # because the orchestrator already scanned its input. Per
        # Pass 3g §A.5: "the wrapping is part of AgenticBaseAgent.run()".
        input_verdict = await _maybe_safety_scan_input(self, validated, ctx)
        if input_verdict is not None and input_verdict.decision == "block":
            return AgentResult(
                output={
                    "blocked": True,
                    "block_reason": input_verdict.user_facing_message
                    or "Input failed safety checks.",
                },
                score=None,
                reasoning="safety_input_block",
                retry_count=0,
                escalated=False,
            )
        # If redacted, the gate populated redacted_text but the
        # specialist's input schema doesn't have a generic "text"
        # field we can swap. The redacted text lives in
        # ctx.extra['safety_redacted_text'] for agents that opt in to
        # consuming it; a future agent-by-agent migration can wire it
        # into specific input fields.
        if input_verdict is not None and input_verdict.decision == "redact":
            ctx = ctx.model_copy(
                update={
                    "extra": {
                        **ctx.extra,
                        "safety_redacted_text": input_verdict.redacted_text,
                    }
                }
            )

        if not self.uses_self_eval:
            output = await self.run(validated, ctx)
            output = await _maybe_safety_scan_output(self, output, ctx, input_verdict)
            return AgentResult(
                output=output,
                score=None,
                reasoning=None,
                retry_count=0,
                escalated=False,
            )

        async def _factory(feedback: str | None) -> Any:
            # On retry, feedback is the critic's reasoning. We stash
            # it in `ctx.extra` so the agent's run() can read it
            # without changing its signature. The agent decides
            # whether/how to surface it (e.g. inject into prompt).
            attempt_ctx = ctx.model_copy(
                update={
                    "extra": {**ctx.extra, "critic_feedback": feedback},
                }
            )
            return await self.run(validated, attempt_ctx)

        result = await evaluate_with_retry(
            agent_name=self.name,
            request=request_str,
            coro_factory=_factory,
            session=ctx.session,
            critic=self._critic(),
            threshold=self.eval_threshold,
            max_retries=self.eval_max_retries,
            user_id=ctx.user_id,
            call_chain_id=ctx.chain.root_id,
            limiter=self._limiter(),
        )
        # Output scan even on the eval-with-retry path. The eval loop
        # produces a single best output (after retries); we scan that
        # one before handing back to the caller.
        result.output = await _maybe_safety_scan_output(
            self, result.output, ctx, input_verdict
        )
        return result

    # ── AgenticCallee protocol (used by call_agent) ───────────────

    async def run_agentic(
        self,
        payload: dict[str, Any] | BaseModel,
        chain: CallChain,
    ) -> AgentCallResult:
        """Implements AgenticCallee. Called by `call_agent` when
        another agent invokes this one.

        The session is recovered from `chain.user_id`'s context —
        but chain doesn't carry a session. Concretely, the calling
        agent's ctx.session is what threads through; we receive it
        via call_agent's session parameter and reconstruct an
        AgentContext here.

        For the protocol to work cleanly, callers MUST invoke
        `call_agent(name, payload, session=..., chain=...)` and the
        primitive threads `session` into a wrapper that lands here
        with a fresh AgentContext. (D6's call_agent already does
        this for all the chain-management; the base class just
        materializes a context the subclass can consume.)
        """
        # We rebuild an AgentContext from the call_agent boundary.
        # The session lives in the communication primitive's
        # contextvar — call_agent sets it before invoking us. If
        # it's missing, we raise: run_agentic should never be
        # called outside the call_agent path.
        session = get_active_session()
        if session is None:
            raise RuntimeError(
                f"AgenticBaseAgent {self.name!r}.run_agentic called "
                "outside an active call_agent context — no session "
                "available. Use call_agent() to invoke."
            )
        ctx = AgentContext(
            user_id=chain.user_id,
            chain=chain,
            session=session,
            permissions=frozenset(),
        )
        result = await self.execute(payload, ctx)
        # AgentResult → AgentCallResult adapter. Status maps:
        #   escalated=True  → status='error' (best-effort returned)
        #   else            → status='ok'
        return AgentCallResult(
            callee=self.name,
            output=result.output,
            status="error" if result.escalated else "ok",
            error=result.reasoning if result.escalated else None,
            duration_ms=0,
        )

    # ── helpers exposed to subclasses ─────────────────────────────

    def memory(self, ctx: AgentContext) -> MemoryStore:
        """Return a MemoryStore bound to the active session.

        Raises if `uses_memory=False` so an opted-out agent that
        accidentally calls into memory is caught at dev time
        instead of silently writing rows."""
        if not self.uses_memory:
            raise RuntimeError(
                f"Agent {self.name!r} has uses_memory=False but tried "
                "to access self.memory(ctx)."
            )
        return MemoryStore(ctx.session)

    async def tool_call(
        self,
        tool_name: str,
        args: dict[str, Any] | BaseModel,
        ctx: AgentContext,
    ) -> ToolCallResult:
        """Run a registered tool via the executor. The tool's audit
        row carries this agent's name + the active call_chain_id."""
        if not self.uses_tools:
            raise RuntimeError(
                f"Agent {self.name!r} has uses_tools=False but tried "
                "to call tool {tool_name!r}."
            )
        executor = ToolExecutor(ctx.session)
        return await executor.execute(
            tool_name,
            args,
            context=ToolCallContext(
                agent_name=self.name,
                user_id=ctx.user_id,
                permissions=ctx.permissions,
                call_chain_id=ctx.chain.root_id,
            ),
        )

    async def call(
        self,
        callee_name: str,
        payload: dict[str, Any] | BaseModel,
        ctx: AgentContext,
    ) -> AgentCallResult:
        """Invoke another agentic agent. Threads the active chain
        so root_id propagates and cycle detection stays accurate.

        The session-binding contextvar is managed by `call_agent`
        itself in the communication primitive — we don't double-
        bind here. That keeps the contextvar lifecycle local to
        one source of truth and makes proactive dispatch (which
        also goes through call_agent) work without mirroring the
        wrapper logic."""
        if not self.uses_inter_agent:
            raise RuntimeError(
                f"Agent {self.name!r} has uses_inter_agent=False but "
                f"tried to call {callee_name!r}."
            )
        return await call_agent(
            callee_name,
            payload=payload,
            session=ctx.session,
            chain=ctx.chain,
        )

    # ── customization hooks (override per agent if needed) ────────

    def _critic(self) -> Critic:
        """Construct the Critic. Default uses Critic.default()
        (Haiku, temperature=0). Override if your agent wants a
        different judge model — but log a reason; cross-agent
        consistency on the critic is a feature, not a bug."""
        return Critic.default()

    def _limiter(self) -> EscalationLimiter:
        """The escalation rate limiter. Default = process-local
        singleton. Override only in tests where you want isolation."""
        return escalation_limiter

    def _request_for_eval(self, input: _InputT) -> str:
        """Build the string the critic sees as 'the user request'.

        Default: serialize the input model as JSON. Override if a
        text field in your input is the actual question (the
        full JSON dump might be noisy for the critic)."""
        try:
            return input.model_dump_json()
        except Exception:  # noqa: BLE001
            return repr(input)

    # ── private ────────────────────────────────────────────────────

    def _validate_input(
        self, input: _InputT | dict[str, Any]
    ) -> _InputT:
        """Coerce dict → input_schema instance. Already-an-instance
        passthroughs unchanged; bad shapes raise pydantic
        ValidationError (caller boundary problem, not an agent
        runtime failure)."""
        if isinstance(input, BaseModel):
            if isinstance(input, self.input_schema):
                return input  # type: ignore[return-value]
            return self.input_schema.model_validate(  # type: ignore[return-value]
                input.model_dump()
            )
        return self.input_schema.model_validate(input)  # type: ignore[return-value]


# ── Safety scanning helpers (Pass 3g §A.5 integration) ──────────────


# Agents whose execute() does NOT need an inner safety scan because
# the orchestrator already scanned upstream. Add to this set with
# care — it should remain very small (only the Supervisor in v1).
_SAFETY_SCAN_EXEMPT_AGENTS = frozenset({"supervisor"})


async def _maybe_safety_scan_input(
    agent: "AgenticBaseAgent[Any]",
    validated_input: BaseModel,
    ctx: AgentContext,
) -> Any:
    """Run input-side safety scan if applicable.

    Returns the SafetyVerdict or None. Returning None means "no scan
    happened" (e.g. exempt agent, or no extractable text from input).

    Lazy imports of the safety primitive so this module stays light
    when safety isn't in play (pure unit tests of memory / tools etc.).
    """
    if agent.name in _SAFETY_SCAN_EXEMPT_AGENTS:
        return None
    text = _extract_input_text(validated_input)
    if not text:
        return None
    try:
        from app.agents.primitives.safety import get_default_gate
    except Exception:  # noqa: BLE001 — Presidio not installed in this env
        return None
    gate = get_default_gate()
    return await gate.scan_input(
        text,
        student_id=ctx.user_id,
        agent_name=agent.name,
    )


async def _maybe_safety_scan_output(
    agent: "AgenticBaseAgent[Any]",
    output: Any,
    ctx: AgentContext,
    input_verdict: Any,
) -> Any:
    """Run output-side safety scan, redact/block if needed.

    Returns the (possibly modified) output. Block replaces the output
    with a templated block message; redact substitutes the redacted
    text. Allow/warn pass through unchanged.
    """
    if agent.name in _SAFETY_SCAN_EXEMPT_AGENTS:
        return output
    text = _extract_output_text(output)
    if not text:
        return output
    try:
        from app.agents.primitives.safety import get_default_gate
    except Exception:  # noqa: BLE001
        return output
    gate = get_default_gate()
    # Pull input PII hits from the input verdict so the output diff
    # logic doesn't false-positive on echoed input PII.
    input_pii_hits = None
    if input_verdict is not None:
        # Findings carry evidence; we don't have the raw PiiHits here,
        # but the diff scanner accepts None and treats it as "no input
        # PII to compare" — generous on echo handling.
        pass
    output_verdict = await gate.scan_output(
        text,
        student_id=ctx.user_id,
        agent_name=agent.name,
        input_pii_hits=input_pii_hits,
    )
    if output_verdict.decision == "block":
        if isinstance(output, dict):
            output = {
                **output,
                "blocked": True,
                "block_reason": "safety_output",
                "output_text": (
                    output_verdict.user_facing_message or "Response blocked."
                ),
            }
        else:
            output = (
                output_verdict.user_facing_message or "Response blocked."
            )
    elif output_verdict.decision == "redact" and output_verdict.redacted_text:
        if isinstance(output, dict):
            output = {**output, "output_text": output_verdict.redacted_text}
        else:
            output = output_verdict.redacted_text
    return output


def _extract_input_text(input_obj: BaseModel) -> str | None:
    """Best-effort string extraction from a validated input model.

    Walks the model's fields looking for the first text-typed value
    on a known key (user_message, question, message, task, prompt).
    Falls back to None if nothing matches — caller skips the scan.
    """
    candidates = ("user_message", "question", "message", "task", "prompt")
    try:
        data = input_obj.model_dump()
    except Exception:  # noqa: BLE001
        return None
    for key in candidates:
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _extract_output_text(output: Any) -> str | None:
    """Best-effort string extraction from a specialist's output."""
    if output is None:
        return None
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("output_text", "answer", "response", "text"):
            val = output.get(key)
            if isinstance(val, str) and val:
                return val
    return None


__all__ = [
    "AgentContext",
    "AgentInput",
    "AgentResult",
    "AgenticBaseAgent",
]
