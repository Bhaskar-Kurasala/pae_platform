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

_PROMPT = (Path(__file__).parent / "prompts" / "disrupt_prevention.md").read_text()

_MIN_INACTIVE_DAYS = 3


@register
class DisruptPreventionAgent(BaseAgent):
    name = "disrupt_prevention"
    description = "Detects disengaged students and generates personalized re-engagement messages."
    trigger_conditions = [
        "re-engage",
        "inactive student",
        "engagement check",
        "churn prevention",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=1024,
        )

    async def execute(self, state: AgentState) -> AgentState:
        days_inactive: int = int(state.context.get("days_inactive", 0))

        # No action needed for recently active students
        if days_inactive < _MIN_INACTIVE_DAYS:
            no_action: dict[str, Any] = {
                "action": "none",
                "reason": f"Student active within {days_inactive} days — no re-engagement needed.",
                "days_inactive": days_inactive,
            }
            return state.model_copy(
                update={
                    "response": json.dumps(no_action, indent=2),
                    "context": {**state.context, "re_engagement": no_action},
                }
            )

        last_lesson = state.context.get("last_lesson", "an earlier lesson")
        streak_before = state.context.get("streak_before", 0)
        student_name = state.context.get("student_name", "there")

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Student {student_name} has been inactive for {days_inactive} days.\n"
                    f"Last lesson completed: {last_lesson}\n"
                    f"Previous streak: {streak_before} days\n\n"
                    "Write a personalized, warm re-engagement message. "
                    "Reference their specific progress. Be encouraging, not guilt-tripping. "
                    "Include one concrete next step they can take in under 10 minutes."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        message = str(response.content)

        result: dict[str, Any] = {
            "action": "send_message",
            "days_inactive": days_inactive,
            "message": message,
            "channel": "email",
        }

        return state.model_copy(
            update={
                "response": json.dumps(result, indent=2),
                "context": {**state.context, "re_engagement": result},
            }
        )
