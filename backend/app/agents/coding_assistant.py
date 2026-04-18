from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "coding_assistant.md").read_text()


@register
class CodingAssistantAgent(BaseAgent):
    name = "coding_assistant"
    description = "Provides PR-style code review comments for student GitHub submissions. More conversational than code_review agent."
    trigger_conditions = [
        "help with code",
        "pr review",
        "coding help",
        "debug",
        "fix my code",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        code = state.context.get("code", state.task)

        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Please review this code and provide PR-style feedback:\n\n"
                    f"```\n{code}\n```\n\n"
                    "Be encouraging, friendly, and focus on helping the student learn. "
                    "Format as GitHub PR review comments in markdown."
                )
            ),
        ]

        llm = self._build_llm()
        response = await llm.ainvoke(messages)
        content = str(response.content)

        return state.model_copy(
            update={
                "response": content,
                "tools_used": state.tools_used + ["coding_assistant"],
            }
        )
