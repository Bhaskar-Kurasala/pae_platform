import time
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

    async def log_action(self, state: AgentState, status: str = "completed", duration_ms: int = 0) -> None:
        """Persist agent action to agent_actions table. Non-blocking."""
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.agent_action import AgentAction

            async with AsyncSessionLocal() as session:
                action = AgentAction(
                    agent_name=self.name,
                    student_id=state.student_id or None,
                    action_type="execute",
                    input_data={"task": state.task, "context_keys": list(state.context.keys())},
                    output_data={
                        "response_length": len(state.response or ""),
                        "tools_used": state.tools_used,
                        "evaluation_score": state.evaluation_score,
                    },
                    status=status,
                    error_message=state.error,
                    duration_ms=duration_ms,
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
