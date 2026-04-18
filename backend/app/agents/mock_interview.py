from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "mock_interview.md").read_text()


@register
class MockInterviewAgent(BaseAgent):
    name = "mock_interview"
    description = "Conducts system design mock interviews for AI engineering roles. Real Claude implementation."
    trigger_conditions = [
        "mock interview",
        "interview practice",
        "system design",
        "interview prep",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    def _build_messages(self, state: AgentState) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=_PROMPT)]

        # Replay full interview conversation history
        for turn in state.conversation_history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=state.task))
        return messages

    async def execute(self, state: AgentState) -> AgentState:
        llm = self._build_llm()
        messages = self._build_messages(state)

        response = await llm.ainvoke(messages)
        content = str(response.content)

        return state.model_copy(
            update={
                "response": content,
                "tools_used": state.tools_used + ["mock_interview"],
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Valid if response contains a question or structured feedback."""
        response = state.response or ""
        has_question = "?" in response
        has_feedback = any(
            word in response.lower()
            for word in ["feedback", "good", "consider", "improvement", "strong", "weak"]
        )
        score = 0.9 if (has_question or has_feedback) else 0.5
        return state.model_copy(update={"evaluation_score": score})
