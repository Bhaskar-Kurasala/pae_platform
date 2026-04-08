import json
from pathlib import Path
from typing import Any

import structlog

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent / "prompts" / "peer_matching.md"

_MOCK_PEERS: list[dict[str, Any]] = [
    {
        "name": "Alex Chen",
        "level": "intermediate",
        "topics": ["RAG", "FastAPI", "LangGraph"],
        "timezone": "UTC-5",
        "goal": "Build production AI apps",
    },
    {
        "name": "Priya Sharma",
        "level": "beginner",
        "topics": ["RAG", "Python", "Pydantic"],
        "timezone": "UTC+5:30",
        "goal": "Transition from data science to AI engineering",
    },
    {
        "name": "Jordan Lee",
        "level": "advanced",
        "topics": ["LangGraph", "Pinecone", "LLM evaluation"],
        "timezone": "UTC+0",
        "goal": "Land senior AI engineer role at FAANG",
    },
]


@register
class PeerMatchingAgent(BaseAgent):
    name = "peer_matching"
    description = "Matches students with study partners based on skill level and learning goals. Stub."
    trigger_conditions = [
        "study partner",
        "peer match",
        "find peers",
        "study group",
    ]
    model = "claude-sonnet-4-6"

    async def execute(self, state: AgentState) -> AgentState:
        # TODO: implement real matching algorithm using student embeddings and skill overlap
        student_topics: list[str] = state.context.get("topics", ["RAG", "FastAPI"])
        # TODO: use student_level in real matching algorithm
        _student_level: str = state.context.get("level", "intermediate")

        # Find best mock peer by topic overlap
        best_peer = _MOCK_PEERS[0]
        best_overlap: list[str] = []

        for peer in _MOCK_PEERS:
            shared = list(set(student_topics) & set(peer["topics"]))
            if len(shared) > len(best_overlap):
                best_peer = peer
                best_overlap = shared

        similarity = round(len(best_overlap) / max(len(student_topics), 1), 2)

        match: dict[str, Any] = {
            "matched_with": best_peer["name"],
            "similarity_score": min(0.95, similarity + 0.35),  # Boost for display
            "shared_topics": best_overlap or student_topics[:2],
            "suggested_activity": "Pair code review",
            "peer_level": best_peer["level"],
            "peer_timezone": best_peer["timezone"],
            "peer_goal": best_peer["goal"],
        }

        return state.model_copy(
            update={
                "response": json.dumps(match, indent=2),
                "context": {**state.context, "peer_match": match},
            }
        )
