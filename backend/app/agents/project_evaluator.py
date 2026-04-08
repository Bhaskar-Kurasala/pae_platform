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

_PROMPT = (Path(__file__).parent / "prompts" / "project_evaluator.md").read_text()

_DEFAULT_RUBRIC = {
    "architecture": "Does the solution use appropriate patterns (RAG, agents, async)?",
    "code_quality": "Is the code production-ready with type hints, logging, error handling?",
    "correctness": "Does the solution solve the stated problem correctly?",
    "documentation": "Is the code well-documented with clear README and docstrings?",
    "innovation": "Does the solution demonstrate creativity and depth of understanding?",
}


@register
class ProjectEvaluatorAgent(BaseAgent):
    name = "project_evaluator"
    description = "Evaluates capstone project submissions against a rubric. Returns detailed feedback with score."
    trigger_conditions = [
        "evaluate project",
        "capstone review",
        "grade submission",
        "project feedback",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=1024,
        )

    async def execute(self, state: AgentState) -> AgentState:
        submission = state.context.get("submission", state.task)
        rubric = state.context.get("rubric", _DEFAULT_RUBRIC)

        llm = self._build_llm()
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Evaluate this capstone project submission:\n\n{submission}\n\n"
                    f"Rubric dimensions:\n{json.dumps(rubric, indent=2)}\n\n"
                    "Return a JSON object with: score (0-100), dimension_scores (dict), "
                    "strengths (list), improvements (list), overall_feedback (str), and approved (bool, score >= 70)."
                )
            ),
        ]

        response = await llm.ainvoke(messages)
        raw = str(response.content)

        evaluation: dict[str, Any] = {}
        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            evaluation = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            evaluation = {"raw_response": raw, "score": 0, "approved": False}

        return state.model_copy(
            update={
                "response": json.dumps(evaluation, indent=2),
                "context": {**state.context, "evaluation": evaluation},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        try:
            result = json.loads(state.response or "{}")
            score_raw = result.get("score", 0)
            normalized = float(score_raw) / 100.0 if isinstance(score_raw, (int, float)) else 0.5
        except (json.JSONDecodeError, TypeError, ValueError):
            normalized = 0.5
        return state.model_copy(update={"evaluation_score": min(1.0, max(0.0, normalized))})
