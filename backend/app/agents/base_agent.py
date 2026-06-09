import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger()


class AgentState(BaseModel):
    """Shared state that flows through every agent and the MOA graph."""

    student_id: str
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    task: str
    context: dict[str, Any] = Field(default_factory=dict)
    response: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    evaluation_score: float | None = None
    agent_name: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class for all platform agents.

    Subclasses must implement `execute(state)` and define:
      - name: str           — unique identifier used by the registry
      - description: str    — shown in the UI and used by MOA routing
      - trigger_conditions  — list of intent patterns for MOA routing
      - model: str          — Claude model ID to use
    """

    name: str = "base_agent"
    description: str = "Base agent"
    trigger_conditions: list[str] = []
    model: str = "claude-sonnet-4-6"

    def __init__(self) -> None:
        self._log = structlog.get_logger().bind(agent=self.name)

    @abstractmethod
    async def execute(self, state: AgentState) -> AgentState:
        """Execute the agent's main logic and return updated state."""
        ...

    async def evaluate(self, state: AgentState) -> AgentState:
        """Quality-check the response. Override per agent.

        Default: pass-through with score 0.8.
        """
        return state.model_copy(update={"evaluation_score": 0.8})

    def _merge_token_usage(self, state: AgentState, llm_response: Any) -> AgentState:
        """Extract token counts from a LangChain AIMessage and merge into state.metadata.

        Call this after ``llm.ainvoke()`` inside ``execute()``:

            response = await llm.ainvoke(messages)
            state = self._merge_token_usage(state, response)

        Handles both LangChain ``usage_metadata`` (preferred) and the older
        ``response_metadata.usage`` dict that some providers emit.
        """
        usage: dict[str, Any] = {}

        # LangChain >= 0.2 — AIMessage.usage_metadata
        usage_meta = getattr(llm_response, "usage_metadata", None)
        if usage_meta and isinstance(usage_meta, dict):
            usage["input_tokens"] = usage_meta.get("input_tokens", 0)
            usage["output_tokens"] = usage_meta.get("output_tokens", 0)

        # Fallback: response_metadata dict (older langchain-anthropic)
        if not usage:
            resp_meta = getattr(llm_response, "response_metadata", {}) or {}
            raw_usage = resp_meta.get("usage", {})
            if raw_usage:
                usage["input_tokens"] = raw_usage.get("input_tokens", 0)
                usage["output_tokens"] = raw_usage.get("output_tokens", 0)

        if usage:
            return state.model_copy(update={"metadata": {**state.metadata, **usage}})
        return state

    async def log_action(self, state: AgentState, status: str = "completed", duration_ms: int = 0) -> None:
        """Persist agent action to agent_actions table. Non-blocking.

        Token usage (input_tokens, output_tokens) stored in state.metadata is
        written to the AgentAction.metadata column for cost visibility.

        DISC-57 — actor identity is read from ``state.context`` on these keys
        (populated by the caller, not the agent itself):
          - ``actor_id``     — UUID string of the human/service initiator
          - ``actor_role``   — "admin" | "student" | "system" | "service"
          - ``on_behalf_of`` — UUID when an admin runs an agent against a student
        """
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.agent_action import AgentAction

            # Log token usage to structured log if present
            input_tokens = state.metadata.get("input_tokens")
            output_tokens = state.metadata.get("output_tokens")
            if input_tokens is not None or output_tokens is not None:
                # PR3/C7.1 — emit a structured `llm.call` event per
                # agent run with everything PostHog (or any downstream
                # cost dashboard) needs to compute SUM(cost) BY user.
                # We compute the cost in INR via the existing pricing
                # table in llm_factory; if the model is unknown we
                # emit 0 and rely on the absolute ₹20 circuit breaker.
                from app.agents.llm_factory import estimate_cost_inr
                from app.core.telemetry import capture as telemetry_capture

                cost_inr = estimate_cost_inr(
                    model=self.model,
                    input_tokens=int(input_tokens or 0),
                    output_tokens=int(output_tokens or 0),
                )
                # D19.1 CP2 — D-D canonical agent cost metric. Bounded
                # cardinality (~20 registered agents). Counter sums
                # over time so per-cohort / per-user attribution
                # happens via logs (correlation IDs from CP1), not
                # via metric labels (D-C cardinality discipline).
                if cost_inr:
                    from app.core.metrics import AGENT_COST_INR_TOTAL

                    AGENT_COST_INR_TOTAL.labels(agent_id=self.name).inc(cost_inr)
                # USD too — easier for the Anthropic budget dashboard.
                cost_usd = round(cost_inr / 84.0, 6) if cost_inr else 0.0

                self._log.info(
                    "llm.call",
                    agent_name=self.name,
                    model=self.model,
                    tokens_in=input_tokens,
                    tokens_out=output_tokens,
                    duration_ms=duration_ms,
                    user_id=state.student_id,
                    status=status,
                    cost_estimate_usd=cost_usd,
                    cost_estimate_inr=cost_inr,
                )
                # Telemetry is no-op when POSTHOG_KEY is unset
                # (PR3/C3.1). Fire-and-forget; the SDK handles queue.
                telemetry_capture(
                    state.student_id or None,
                    "llm.call",
                    {
                        "agent_name": self.name,
                        "model": self.model,
                        "tokens_in": input_tokens,
                        "tokens_out": output_tokens,
                        "duration_ms": duration_ms,
                        "status": status,
                        "cost_estimate_usd": cost_usd,
                        "cost_estimate_inr": cost_inr,
                    },
                )

            async with AsyncSessionLocal() as session:
                output_data: dict[str, Any] = {
                    "response_length": len(state.response or ""),
                    "tools_used": state.tools_used,
                    "evaluation_score": state.evaluation_score,
                }
                if input_tokens is not None:
                    output_data["input_tokens"] = input_tokens
                if output_tokens is not None:
                    output_data["output_tokens"] = output_tokens

                total_tokens = (
                    (input_tokens or 0) + (output_tokens or 0)
                    if (input_tokens is not None or output_tokens is not None)
                    else None
                )

                actor_id_raw = state.context.get("actor_id")
                actor_role = state.context.get("actor_role")
                on_behalf_raw = state.context.get("on_behalf_of")

                def _as_uuid(val: Any) -> Any:
                    if val is None:
                        return None
                    if isinstance(val, uuid.UUID):
                        return val
                    try:
                        return uuid.UUID(str(val))
                    except (ValueError, AttributeError):
                        return None

                # Default actor to the student when the caller didn't name one —
                # preserves pre-DISC-57 behavior for chat traffic while still
                # populating the new columns.
                actor_id = _as_uuid(actor_id_raw)
                if actor_role is None and actor_id_raw is None and state.student_id:
                    # Student-initiated chat: default actor to the student
                    actor_role = "student"
                    actor_id = _as_uuid(state.student_id)
                elif actor_role == "system":
                    # System-initiated: never auto-bind actor_id to a student
                    actor_id = None
                elif actor_role == "admin" and on_behalf_raw and not actor_id_raw:
                    # Defensive: an admin call without actor_id is malformed,
                    # but don't silently relabel as student.
                    pass

                action = AgentAction(
                    agent_name=self.name,
                    student_id=state.student_id or None,
                    action_type="execute",
                    input_data={"task": state.task, "context_keys": list(state.context.keys())},
                    output_data=output_data,
                    tokens_used=total_tokens,
                    status=status,
                    error_message=state.error,
                    duration_ms=duration_ms,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    on_behalf_of=_as_uuid(on_behalf_raw),
                )
                session.add(action)
                await session.commit()
        except Exception as exc:
            self._log.warning("agent.log_action.failed", error=str(exc))

    async def run(self, state: AgentState) -> AgentState:
        """Full pipeline: execute → evaluate → log_action.

        D19.1 CP1.2c — ``agent_id`` is bound to structlog contextvars
        at the canonical run() entry so every log line emitted *during*
        the agent invocation carries it, including lines from non-
        agent code paths the agent transitively calls (DB layer, tool
        functions, LLM providers). Unbound in the finally block so a
        subsequent agent in the same request gets a clean slate.
        """
        # D19.1 CP2 — local import to avoid the metrics module's
        # boot-time registration running before structlog is configured
        # (configure_logging in main.py runs first; metrics.py is small
        # but imports prometheus_client which configures its own
        # process-level multiprocess directory check).
        from app.core.metrics import (
            AGENT_INVOCATION_DURATION_SECONDS,
            AGENT_INVOCATIONS,
        )

        # D19.1 CP3 — manual span per agent invocation. span attributes
        # are bounded-cardinality + non-PII per the privacy denylist;
        # token counts + cost_inr are layered in by log_action below
        # via metadata.
        from app.core.tracing import get_tracer, set_safe_span_attribute

        tracer = get_tracer()
        start_monotonic = time.monotonic()
        status = "completed"
        outcome = "success"
        structlog.contextvars.bind_contextvars(agent_id=self.name)
        with tracer.start_as_current_span(f"agent.{self.name}") as span:
            set_safe_span_attribute(span, "agent_id", self.name)
            set_safe_span_attribute(span, "agent.model", self.model)
            # Kill-switch check — short-circuit before execute() if admin
            # disabled this agent via agent_runtime_config. Never raise from
            # the config-read path; a DB blip must not break agent execution.
            try:
                from sqlalchemy import select as _select

                from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
                from app.models.agent_runtime_config import (
                    AgentRuntimeConfig as _AgentRuntimeConfig,
                )

                async with _AsyncSessionLocal() as _session:
                    _cfg = (
                        await _session.execute(
                            _select(_AgentRuntimeConfig).where(
                                _AgentRuntimeConfig.name == self.name
                            )
                        )
                    ).scalar_one_or_none()
                    if _cfg is not None and not _cfg.is_enabled:
                        self._log.info("agent.run.disabled_by_admin")
                        set_safe_span_attribute(span, "agent.outcome", "disabled")
                        structlog.contextvars.unbind_contextvars("agent_id")
                        return state.model_copy(
                            update={
                                "error": f"Agent {self.name} is currently disabled by admin",
                                "response": None,
                                "agent_name": self.name,
                            }
                        )
            except Exception:
                pass
            try:
                self._log.info("agent.run.start", task_length=len(state.task))
                state = await self.execute(state)
                state = await self.evaluate(state)
                state = state.model_copy(update={"agent_name": self.name})
                self._log.info("agent.run.complete", score=state.evaluation_score)
            except Exception as exc:
                status = "error"
                outcome = "error"
                state = state.model_copy(
                    update={"error": str(exc), "agent_name": self.name}
                )
                self._log.exception("agent.run.error", error=str(exc))
                span.record_exception(exc)
                raise
            finally:
                duration_seconds = time.monotonic() - start_monotonic
                duration_ms = int(duration_seconds * 1000)
                set_safe_span_attribute(span, "agent.outcome", outcome)
                set_safe_span_attribute(span, "agent.duration_ms", duration_ms)
                # Token counts (when present in state.metadata) carry
                # no PII and are critical for cost-per-trace queries
                # in CP4 dashboards.
                tokens_in = state.metadata.get("input_tokens")
                tokens_out = state.metadata.get("output_tokens")
                if tokens_in is not None:
                    set_safe_span_attribute(
                        span, "agent.tokens_in", int(tokens_in)
                    )
                if tokens_out is not None:
                    set_safe_span_attribute(
                        span, "agent.tokens_out", int(tokens_out)
                    )
                AGENT_INVOCATIONS.labels(
                    agent_id=self.name, outcome=outcome
                ).inc()
                AGENT_INVOCATION_DURATION_SECONDS.labels(
                    agent_id=self.name
                ).observe(duration_seconds)
                await self.log_action(state, status=status, duration_ms=duration_ms)
                structlog.contextvars.unbind_contextvars("agent_id")
        return state
