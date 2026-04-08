import json
from pathlib import Path
from typing import Any

import structlog

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent / "prompts" / "deep_capturer.md"


@register
class DeepCapturerAgent(BaseAgent):
    name = "deep_capturer"
    description = "Generates weekly synthesis connecting concepts across the curriculum. Runs on a schedule."
    trigger_conditions = [
        "weekly summary",
        "concept connections",
        "synthesis",
        "big picture",
    ]
    model = "claude-sonnet-4-6"

    async def execute(self, state: AgentState) -> AgentState:
        # TODO: implement real synthesis from student progress and curriculum data
        week_theme = state.context.get("week_theme", "LangGraph Patterns")

        insight: dict[str, Any] = {
            "week_theme": week_theme,
            "connections": [
                {
                    "from": "RAG pipelines",
                    "to": "LangGraph state nodes",
                    "insight": "RAG retrieval can be modelled as a dedicated LangGraph node that enriches state before generation.",
                },
                {
                    "from": "Pydantic validation",
                    "to": "LLM output parsing",
                    "insight": "Using model_validate() on LLM output ensures type safety across every agent boundary.",
                },
                {
                    "from": "Spaced repetition",
                    "to": "Knowledge graph mastery scores",
                    "insight": "SM-2 ease_factor maps directly to concept mastery — high ease = high retention.",
                },
            ],
            "insight": (
                f"This week's theme '{week_theme}' reveals how stateful orchestration "
                "underpins every production AI system. When you design the state schema first, "
                "the agent logic falls naturally into place."
            ),
            "recommended_review": ["LangGraph conditional edges", "Pydantic v2 validators"],
        }

        return state.model_copy(
            update={
                "response": json.dumps(insight, indent=2),
                "context": {**state.context, "weekly_insight": insight},
            }
        )
