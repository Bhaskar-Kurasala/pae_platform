import time
from abc import ABC, abstractmethod
from typing import Any

import structlog

log = structlog.get_logger()


class AgentInput(dict):  # type: ignore[type-arg]
    """Typed dict for agent inputs."""


class AgentOutput(dict):  # type: ignore[type-arg]
    """Typed dict for agent outputs."""


class BaseAgent(ABC):
    """Abstract base class for all platform agents.

    All 18+ agents must subclass this and implement `execute()`.
    The log() method persists actions to agent_actions table.
    The evaluate() method assesses output quality before delivery.
    """

    name: str = "base_agent"
    description: str = "Base agent"

    def __init__(self) -> None:
        self.log = structlog.get_logger().bind(agent=self.name)

    @abstractmethod
    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's main logic.

        Args:
            input_data: Structured input for this agent.

        Returns:
            Structured output from the agent.
        """
        ...

    async def evaluate(self, output: dict[str, Any]) -> dict[str, Any]:
        """Evaluate the quality of the agent output before delivery.

        Override in subclasses for agent-specific quality checks.
        Returns the output dict with an optional `quality_score` key.
        """
        return {**output, "quality_score": 1.0}

    async def run(
        self,
        input_data: dict[str, Any],
        student_id: str | None = None,
    ) -> dict[str, Any]:
        """Orchestrated run: execute → evaluate → log.

        Args:
            input_data: Structured input for this agent.
            student_id: Optional ID of the student this action is for.

        Returns:
            Evaluated and logged agent output.
        """
        start_ms = int(time.monotonic() * 1000)
        status = "completed"
        error_message: str | None = None
        output: dict[str, Any] = {}

        try:
            self.log.info("agent.run.start", input_keys=list(input_data.keys()))
            output = await self.execute(input_data)
            output = await self.evaluate(output)
            self.log.info("agent.run.complete", output_keys=list(output.keys()))
        except Exception as exc:
            status = "error"
            error_message = str(exc)
            self.log.exception("agent.run.error", error=error_message)
            raise
        finally:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            await self._persist_action(
                student_id=student_id,
                input_data=input_data,
                output_data=output,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
                tokens_used=output.get("tokens_used"),
            )

        return output

    async def _persist_action(
        self,
        student_id: str | None,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        status: str,
        error_message: str | None,
        duration_ms: int,
        tokens_used: int | None,
    ) -> None:
        """Persist agent action to database. No-op if DB unavailable."""
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.agent_action import AgentAction

            safe_input = {k: v for k, v in input_data.items() if k != "secret"}
            safe_output = {k: v for k, v in output_data.items() if k != "tokens_used"}

            async with AsyncSessionLocal() as session:
                action = AgentAction(
                    agent_name=self.name,
                    student_id=student_id,
                    action_type="execute",
                    input_data=safe_input,
                    output_data=safe_output,
                    status=status,
                    error_message=error_message,
                    duration_ms=duration_ms,
                    tokens_used=tokens_used,
                )
                session.add(action)
                await session.commit()
        except Exception as exc:
            self.log.warning("agent.persist.failed", error=str(exc))
