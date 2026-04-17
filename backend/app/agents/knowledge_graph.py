import json
from pathlib import Path
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register
from app.core.config import settings

log = structlog.get_logger()

_PROMPT = (Path(__file__).parent / "prompts" / "knowledge_graph.md").read_text()

_MASTERY_THRESHOLD = 0.85

# Full concept catalogue used for gap detection
_ALL_CONCEPTS = [
    "RAG",
    "LangGraph",
    "FastAPI",
    "Pydantic v2",
    "LangChain Tools",
    "Pinecone",
    "Celery",
    "Vector Databases",
    "Embeddings",
    "LLM Evaluation",
]


@register
class KnowledgeGraphAgent(BaseAgent):
    """Updates student concept mastery via EMA and generates an LLM narrative.

    The EMA mastery calculation runs locally (no LLM cost). Claude Haiku is
    then called to produce a human-readable skill gap explanation and 3
    actionable next-learning recommendations.

    TODO (Phase 6): Persist updated_mastery to users.metadata JSONB column
    and sync concept nodes into Pinecone for semantic similarity matching.
    """

    name = "knowledge_graph"
    description = (
        "Updates student's concept mastery map after quiz/exercise completion "
        "and generates personalised skill-gap explanations with next steps."
    )
    trigger_conditions = [
        "update knowledge",
        "concept mastery",
        "knowledge graph",
        "skill map",
    ]
    model = "claude-haiku-4-5"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=512,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_llm(self, llm: ChatAnthropic, mastery: dict[str, float], gaps: list[str]) -> str:
        """Call Claude Haiku to produce a skill-gap narrative and recommendations."""
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Current concept mastery scores (0.0–1.0):\n{json.dumps(mastery, indent=2)}\n\n"
                    f"Concepts with mastery below 0.6 (priority gaps): {gaps}\n\n"
                    "Please provide:\n"
                    "1. A 2-3 sentence narrative explaining the student's current skill landscape\n"
                    "2. An explanation of why these gaps matter for production AI engineering\n"
                    "3. Three specific, actionable next-learning recommendations (numbered list)\n\n"
                    "Keep the response concise and motivating but honest."
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    async def execute(self, state: AgentState) -> AgentState:
        quiz_scores: dict[str, float] = state.context.get("quiz_scores", {})
        existing_mastery: dict[str, float] = state.context.get("concept_mastery", {})

        # ── EMA mastery update (no LLM — deterministic) ───────────────────────
        updated_mastery: dict[str, float] = dict(existing_mastery)
        for concept, score in quiz_scores.items():
            prev = updated_mastery.get(concept, 0.0)
            # EMA: 70% new score, 30% historical — converges quickly on recent performance
            updated_mastery[concept] = round(0.7 * score + 0.3 * prev, 3)

        # Fallback mock mastery if no quiz scores provided
        if not updated_mastery:
            updated_mastery = {"RAG": 0.8, "LangGraph": 0.6, "FastAPI": 0.75}

        newly_mastered = [
            concept
            for concept, score in updated_mastery.items()
            if score >= _MASTERY_THRESHOLD and existing_mastery.get(concept, 0.0) < _MASTERY_THRESHOLD
        ]

        # Priority gaps: concepts below 0.6
        gap_concepts = [
            c for c in _ALL_CONCEPTS if updated_mastery.get(c, 0.0) < 0.6
        ][:3]

        suggested_next = gap_concepts or ["LangChain Tools"]

        # ── LLM narrative (Claude Haiku — fast, cheap) ────────────────────────
        llm_explanation: str = ""
        if settings.anthropic_api_key:
            try:
                llm = self._build_llm()
                llm_explanation = await self._call_llm(llm, updated_mastery, gap_concepts)
            except Exception as exc:
                self._log.warning("knowledge_graph.llm_failed", error=str(exc))
                llm_explanation = (
                    "Your mastery map has been updated. "
                    f"Focus on: {', '.join(suggested_next)} to close your current skill gaps."
                )
        else:
            llm_explanation = (
                "Your mastery map has been updated. "
                f"Priority concepts to study: {', '.join(suggested_next)}."
            )

        result: dict[str, Any] = {
            "updated_concepts": updated_mastery,
            "newly_mastered": newly_mastered,
            "suggested_next": suggested_next,
            "explanation": llm_explanation,
        }

        return state.model_copy(
            update={
                "response": json.dumps(result, indent=2),
                "context": {**state.context, "concept_mastery": updated_mastery},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        try:
            result = json.loads(state.response or "{}")
            has_mastery = "updated_concepts" in result
            has_explanation = bool(result.get("explanation", ""))
            score = 0.9 if (has_mastery and has_explanation) else (0.6 if has_mastery else 0.3)
        except (json.JSONDecodeError, TypeError):
            score = 0.3
        return state.model_copy(update={"evaluation_score": score})
