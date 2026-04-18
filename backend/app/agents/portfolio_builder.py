import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "portfolio_builder.md").read_text()


@register
class PortfolioBuilderAgent(BaseAgent):
    name = "portfolio_builder"
    description = "Generates a markdown portfolio entry from student's completed project."
    trigger_conditions = [
        "build portfolio",
        "portfolio",
        "showcase project",
        "write up",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 1024):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        projects: list[dict[str, Any]] = state.context.get("projects", [])

        if not projects:
            projects = [{"title": state.task, "description": "AI engineering project", "technologies": []}]

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Create a polished markdown portfolio entry for these completed projects:\n\n"
                    f"```json\n{json.dumps(projects, indent=2)}\n```\n\n"
                    "Format as a professional GitHub README-style portfolio section. "
                    "Highlight technical depth, production-readiness, and real-world impact. "
                    "Include tech stack badges, key decisions, and measurable outcomes where possible."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        content = str(response.content)

        return state.model_copy(
            update={
                "response": content,
                "context": {**state.context, "portfolio_markdown": content},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Valid portfolio has at least one markdown heading."""
        response = state.response or ""
        has_heading = "#" in response
        has_content = len(response.strip()) > 100
        score = 0.9 if (has_heading and has_content) else 0.4
        return state.model_copy(update={"evaluation_score": score})
