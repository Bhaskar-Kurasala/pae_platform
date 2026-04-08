import json
from pathlib import Path
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "progress_report.md").read_text()


@register
class ProgressReportAgent(BaseAgent):
    name = "progress_report"
    description = "Generates human-readable weekly progress report for a student."
    trigger_conditions = [
        "progress report",
        "weekly report",
        "my progress",
        "how am I doing",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=1024,
        )

    async def execute(self, state: AgentState) -> AgentState:
        progress: dict[str, Any] = state.context.get("progress", {})
        quiz_scores: dict[str, Any] = state.context.get("quiz_scores", {})
        streak_days: int = int(state.context.get("streak_days", 0))
        lessons_completed: int = int(state.context.get("lessons_completed", 0))

        progress_summary = {
            "lessons_completed": lessons_completed,
            "streak_days": streak_days,
            "quiz_scores": quiz_scores,
            "additional_progress": progress,
        }

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Generate a warm, encouraging weekly progress report for student {state.student_id}.\n\n"
                    f"Progress data:\n{json.dumps(progress_summary, indent=2)}\n\n"
                    "Include: what they accomplished this week, strengths, areas to improve, "
                    "specific next steps, and a motivational closing. Tone: warm coach, not robot."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        content = str(response.content)

        return state.model_copy(
            update={
                "response": content,
                "context": {**state.context, "report_generated": True},
            }
        )
