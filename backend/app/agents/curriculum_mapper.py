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

_PROMPT = (Path(__file__).parent / "prompts" / "curriculum_mapper.md").read_text()


@register
class CurriculumMapperAgent(BaseAgent):
    name = "curriculum_mapper"
    description = "Maps ingested content to existing curriculum structure and suggests lesson ordering updates."
    trigger_conditions = [
        "map curriculum",
        "update curriculum",
        "lesson order",
        "curriculum update",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=1024,
        )

    async def execute(self, state: AgentState) -> AgentState:
        content_metadata = state.context.get("content_metadata", {})

        if not content_metadata:
            content_metadata = {"title": state.task, "topics": [], "content_type": "unknown"}

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Map the following ingested content into the curriculum:\n\n"
                    f"```json\n{json.dumps(content_metadata, indent=2)}\n```\n\n"
                    "Return a JSON object with suggested_position, topics_covered, and prerequisites."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        raw = str(response.content)

        mapping: dict[str, Any] = {}
        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            mapping = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            mapping = {
                "suggested_position": "after lesson 3",
                "topics_covered": content_metadata.get("topics", []),
                "prerequisites": [],
                "raw_response": raw,
            }

        return state.model_copy(
            update={
                "response": json.dumps(mapping, indent=2),
                "context": {**state.context, "curriculum_mapping": mapping},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        try:
            mapping = json.loads(state.response or "{}")
            has_position = "suggested_position" in mapping
            has_topics = "topics_covered" in mapping
            score = 0.9 if (has_position and has_topics) else 0.5
        except (json.JSONDecodeError, TypeError):
            score = 0.3
        return state.model_copy(update={"evaluation_score": score})
