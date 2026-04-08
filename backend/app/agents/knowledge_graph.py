import json
from pathlib import Path
from typing import Any

import structlog

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent / "prompts" / "knowledge_graph.md"

_MASTERY_THRESHOLD = 0.85


@register
class KnowledgeGraphAgent(BaseAgent):
    name = "knowledge_graph"
    description = "Updates student's concept mastery map after quiz/exercise completion. Stub for Pinecone/graph integration."
    trigger_conditions = [
        "update knowledge",
        "concept mastery",
        "knowledge graph",
        "skill map",
    ]
    model = "claude-sonnet-4-6"

    async def execute(self, state: AgentState) -> AgentState:
        # TODO: store in JSONB column and update Pinecone concept graph
        quiz_scores: dict[str, float] = state.context.get("quiz_scores", {})
        existing_mastery: dict[str, float] = state.context.get("concept_mastery", {})

        # Merge quiz scores into mastery map with exponential moving average
        updated_mastery: dict[str, float] = dict(existing_mastery)
        for concept, score in quiz_scores.items():
            prev = updated_mastery.get(concept, 0.0)
            # EMA weight: 70% new score, 30% history
            updated_mastery[concept] = round(0.7 * score + 0.3 * prev, 3)

        # Fallback mock mastery if no quiz scores provided
        if not updated_mastery:
            updated_mastery = {"RAG": 0.8, "LangGraph": 0.6, "FastAPI": 0.75}

        newly_mastered = [
            concept for concept, score in updated_mastery.items()
            if score >= _MASTERY_THRESHOLD and existing_mastery.get(concept, 0.0) < _MASTERY_THRESHOLD
        ]

        # Suggest next concepts based on gaps
        all_concepts = ["RAG", "LangGraph", "FastAPI", "Pydantic v2", "LangChain Tools", "Pinecone", "Celery"]
        suggested_next: list[str] = [
            c for c in all_concepts
            if updated_mastery.get(c, 0.0) < 0.6
        ][:3]

        result: dict[str, Any] = {
            "updated_concepts": updated_mastery,
            "newly_mastered": newly_mastered,
            "suggested_next": suggested_next or ["LangChain Tools"],
        }

        return state.model_copy(
            update={
                "response": json.dumps(result, indent=2),
                "context": {**state.context, "concept_mastery": updated_mastery},
            }
        )
