from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "community_celebrator.md").read_text()


@register
class CommunityCelebratorAgent(BaseAgent):
    name = "community_celebrator"
    description = "Generates celebration messages and announcements for student milestones."
    trigger_conditions = [
        "celebrate",
        "milestone",
        "achievement",
        "completed course",
        "congratulate",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        milestone = state.context.get("milestone", state.task)
        student_name = state.context.get("student_name", "our student")
        format_type = state.context.get("format", "announcement")

        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Generate a celebration message for this milestone:\n\n"
                    f"Student: {student_name}\n"
                    f"Milestone: {milestone}\n"
                    f"Format: {format_type} (one of: tweet-style, announcement, personal-note)\n\n"
                    "Be upbeat, specific, and inspiring. Avoid generic phrases. "
                    "Reference the actual achievement and what it means for their career."
                )
            ),
        ]

        llm = self._build_llm()
        response = await llm.ainvoke(messages)
        content = str(response.content)

        return state.model_copy(
            update={
                "response": content,
                "context": {**state.context, "celebration_message": content},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Good celebration message is non-empty and upbeat."""
        response = state.response or ""
        has_content = len(response.strip()) > 30
        score = 0.9 if has_content else 0.3
        return state.model_copy(update={"evaluation_score": score})
