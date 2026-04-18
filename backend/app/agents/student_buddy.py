from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "student_buddy.md").read_text()


@register
class StudentBuddyAgent(BaseAgent):
    name = "student_buddy"
    description = "Short, focused explanations tailored to student's current lesson and knowledge level. Like a study partner."
    trigger_conditions = [
        "quick explanation",
        "tldr",
        "summarize",
        "simple explanation",
        "eli5",
        "explain briefly",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    def _build_messages(self, state: AgentState) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=_PROMPT)]

        # Include recent conversation history for context (last 4 turns)
        for turn in state.conversation_history[-4:]:
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

        return state.model_copy(update={"response": content})

    async def evaluate(self, state: AgentState) -> AgentState:
        """Good buddy response is concise (< 200 words)."""
        response = state.response or ""
        word_count = len(response.split())
        score = 0.9 if word_count <= 200 else 0.6
        return state.model_copy(update={"evaluation_score": score})
