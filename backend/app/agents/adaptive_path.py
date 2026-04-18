import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "adaptive_path.md").read_text()


@register
class AdaptivePathAgent(BaseAgent):
    name = "adaptive_path"
    description = "Adjusts student's learning path based on quiz performance and identifies knowledge gaps."
    trigger_conditions = [
        "learning path",
        "what should I study",
        "next lesson",
        "study plan",
        "adapt path",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        quiz_scores: dict[str, Any] = state.context.get("quiz_scores", {})
        progress: dict[str, Any] = state.context.get("progress", {})

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Student quiz scores by concept:\n{json.dumps(quiz_scores, indent=2)}\n\n"
                    f"Current progress:\n{json.dumps(progress, indent=2)}\n\n"
                    f"Student task: {state.task}\n\n"
                    "Analyze the gaps and return a JSON learning path recommendation with: "
                    "next_lessons (list), skip_lessons (list), focus_concepts (list), "
                    "estimated_completion_days (int), and reasoning (str)."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        raw = str(response.content)

        recommendation: dict[str, Any] = {}
        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            recommendation = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            recommendation = {"raw_response": raw, "next_lessons": [], "reasoning": raw}

        return state.model_copy(
            update={
                "response": json.dumps(recommendation, indent=2),
                "context": {**state.context, "learning_path": recommendation},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        try:
            path = json.loads(state.response or "{}")
            has_next = "next_lessons" in path
            has_reasoning = "reasoning" in path
            score = 0.9 if (has_next and has_reasoning) else 0.5
        except (json.JSONDecodeError, TypeError):
            score = 0.3
        return state.model_copy(update={"evaluation_score": score})
