import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "mcq_factory.md").read_text()


@register
class MCQFactoryAgent(BaseAgent):
    name = "mcq_factory"
    description = "Generates multiple-choice questions from lesson content using Claude. Returns structured MCQ JSON array."
    trigger_conditions = [
        "generate questions",
        "create mcq",
        "make quiz",
        "question bank",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self, max_tokens: int = 2048):
        from app.agents.llm_factory import build_llm
        return build_llm(max_tokens=max_tokens)

    async def execute(self, state: AgentState) -> AgentState:
        content = state.context.get("content", state.task)
        conversation_context: str | None = state.context.get("conversation_context")

        context_block = ""
        if conversation_context:
            context_block = (
                f"\n\nStudent's original question (use this to anchor scenario-grounded distractors):\n"
                f"{conversation_context}\n"
            )

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Generate EXACTLY 5 multiple-choice questions following the balanced mix "
                    f"(foundation recall → application A → application B → analysis/tradeoff → misconception trap) "
                    f"for the following content:\n\n"
                    f"{content}"
                    f"{context_block}\n"
                    "Return ONLY the JSON array — no surrounding text, no markdown fences."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        raw = str(response.content)

        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            mcqs: list[Any] = json.loads(raw)
            if not isinstance(mcqs, list):
                mcqs = [mcqs]
        except (json.JSONDecodeError, IndexError):
            mcqs = [{"raw_response": raw}]

        return state.model_copy(
            update={
                "response": json.dumps(mcqs, indent=2),
                "context": {**state.context, "generated_mcqs": mcqs},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Score 0.9 if valid JSON array with >= 1 question, else 0.3."""
        try:
            raw = state.response or "[]"
            questions = json.loads(raw)
            score = 0.9 if isinstance(questions, list) and len(questions) >= 1 else 0.3
        except (json.JSONDecodeError, TypeError):
            score = 0.3
        return state.model_copy(update={"evaluation_score": score})
