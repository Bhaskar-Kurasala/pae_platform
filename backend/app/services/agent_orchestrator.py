"""Agent Orchestrator Service.

Wraps the MOA graph, manages conversation history in Redis,
and provides a clean interface for the chat API route.
"""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import AgentState
from app.agents.moa import MOAGraphState, get_moa_graph

log = structlog.get_logger()

_HISTORY_TTL = 3600  # 1 hour


async def _get_redis() -> Any:
    """Get Redis client, or None if unavailable."""
    try:
        from app.core.redis import get_redis

        return await get_redis()
    except Exception:
        return None


def _conv_key(conversation_id: str) -> str:
    from app.core.redis import namespaced_key

    return namespaced_key("conv", conversation_id)


async def _load_history(
    redis: Any, conversation_id: str
) -> list[dict[str, Any]]:
    if not redis:
        return []
    try:
        raw = await redis.get(_conv_key(conversation_id))
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return []


async def _save_history(
    redis: Any,
    conversation_id: str,
    history: list[dict[str, Any]],
) -> None:
    if not redis:
        return
    try:
        await redis.setex(
            _conv_key(conversation_id),
            _HISTORY_TTL,
            json.dumps(history),
        )
    except Exception as exc:
        log.warning("orchestrator.save_history.failed", error=str(exc))


class AgentOrchestratorService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def chat(
        self,
        student_id: str,
        message: str,
        conversation_id: str | None = None,
        agent_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Route a student message through the MOA and return a response.

        Args:
            student_id: UUID string of the authenticated student.
            message: The student's message text.
            conversation_id: Optional session ID for history continuity.
            agent_name: If provided, bypass classification and use this agent.
            context: Optional additional context (code, quiz_state, etc.).

        Returns:
            Dict with: response, agent_name, evaluation_score, conversation_id.
        """
        conv_id = conversation_id or str(uuid.uuid4())
        redis = await _get_redis()
        history = await _load_history(redis, conv_id)

        initial_state = AgentState(
            student_id=student_id,
            task=message,
            conversation_history=history,
            context=context or {},
        )

        graph_input: MOAGraphState = {
            "messages": [],
            "agent_state": initial_state,
            "routed_to": agent_name or "",
            "final_response": "",
            "evaluation_score": 0.0,
        }

        # If agent explicitly requested, skip classification
        if agent_name:
            graph = get_moa_graph()
            # Run the specific agent directly
            from app.agents.registry import get_agent

            try:
                agent = get_agent(agent_name)
                result_state = await agent.run(initial_state)
            except KeyError:
                result_state = initial_state.model_copy(
                    update={
                        "response": f"Agent '{agent_name}' not found. Available: socratic_tutor, code_review, adaptive_quiz",
                        "agent_name": "system",
                    }
                )
            used_agent = result_state.agent_name or agent_name
        else:
            graph = get_moa_graph()
            result = await graph.ainvoke(graph_input)
            result_state = result["agent_state"]
            used_agent = result.get("routed_to", result_state.agent_name or "socratic_tutor")

        # DISC-42 — some agents hand us a str(response.content) that is a Python
        # repr of Anthropic's list-of-dict content (thinking + text blocks).
        # Flatten it here as a safety net so the chat surface never shows a
        # raw repr. flatten_content is a no-op for ordinary strings.
        from app.agents._llm_utils import flatten_content

        response_text = (
            flatten_content(result_state.response)
            or "I couldn't generate a response. Please try again."
        )
        eval_score = result_state.evaluation_score or 0.0

        # Update conversation history
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response_text, "agent": used_agent})
        # Keep last 20 turns
        history = history[-20:]
        await _save_history(redis, conv_id, history)

        log.info(
            "orchestrator.chat.complete",
            student_id=student_id,
            agent=used_agent,
            score=eval_score,
            conv_id=conv_id,
        )

        return {
            "response": response_text,
            "agent_name": used_agent,
            "evaluation_score": eval_score,
            "conversation_id": conv_id,
        }
