import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

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

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        progress: dict[str, Any] = state.context.get("progress", {})
        quiz_scores: dict[str, Any] = state.context.get("quiz_scores", {})
        skills_touched: int = int(state.context.get("skills_touched", 0))
        streak_days: int = int(state.context.get("streak_days", 0))
        lessons_completed: int = int(state.context.get("lessons_completed", 0))

        progress_summary = {
            "lessons_completed": lessons_completed,
            "skills_touched": skills_touched,
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
        raw = response.content
        # Anthropic extended-thinking responses come back as a list of blocks
        # (thinking + text). Concatenate only the user-visible text blocks.
        if isinstance(raw, list):
            parts: list[str] = []
            for block in raw:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            content = "\n".join(p for p in parts if p)
        else:
            content = str(raw)

        return state.model_copy(
            update={
                "response": content,
                "context": {**state.context, "report_generated": True},
            }
        )
