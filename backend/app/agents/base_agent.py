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
                actor_id = _as_uuid(actor_id_raw) or _as_uuid(state.student_id)
                if actor_role is None and actor_id_raw is None and state.student_id:
                    actor_role = "student"

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
        """Full pipeline: execute → evaluate → log_action."""
        start_ms = int(time.monotonic() * 1000)
        status = "completed"
        try:
            self._log.info("agent.run.start", task_length=len(state.task))
            state = await self.execute(state)
            state = await self.evaluate(state)
            state = state.model_copy(update={"agent_name": self.name})
            self._log.info("agent.run.complete", score=state.evaluation_score)
        except Exception as exc:
            status = "error"
            state = state.model_copy(update={"error": str(exc), "agent_name": self.name})
            self._log.exception("agent.run.error", error=str(exc))
            raise
        finally:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            await self.log_action(state, status=status, duration_ms=duration_ms)
        return state
