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

_PROMPT = (Path(__file__).parent / "prompts" / "peer_matching.md").read_text()

# PHASE 6 NOTE: Real peer matching will use Pinecone vector similarity.
# Each student profile will be embedded using their skill list + learning goals,
# and cosine similarity search will replace this mock list.
# Ticket: WS4-peer-matching-pinecone
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
    """Matches students with study partners and generates personalised outreach messages.

    Matching algorithm: topic-overlap scoring against a mock peer list.
    Phase 6 will replace this with Pinecone vector similarity matching on
    student profile embeddings.
    """

    name = "peer_matching"
    description = (
        "Matches students with study partners based on shared topics and goals, "
        "then generates a personalised connection message explaining the match."
    )
    trigger_conditions = [
        "study partner",
        "peer match",
        "find peers",
        "study group",
    ]
    model = "claude-sonnet-4-6"

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
    async def _generate_outreach(
        self,
        llm: ChatAnthropic,
        peer: dict[str, Any],
        student_topics: list[str],
        student_goal: str,
        shared_topics: list[str],
    ) -> str:
        """Generate a personalised outreach message for the matched peer."""
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"I matched with {peer['name']} as a potential study partner.\n\n"
                    f"My topics: {student_topics}\n"
                    f"My goal: {student_goal}\n\n"
                    f"Their topics: {peer['topics']}\n"
                    f"Their goal: {peer['goal']}\n"
                    f"Their level: {peer['level']}\n"
                    f"Shared topics: {shared_topics}\n\n"
                    "Please write:\n"
                    "1. A 2-sentence explanation of why this is a good match\n"
                    "2. A short, friendly outreach message (3-4 sentences) I can send them\n"
                    "   — mention a specific shared topic and suggest a first activity\n\n"
                    "Keep it natural, not corporate."
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    async def execute(self, state: AgentState) -> AgentState:
        student_topics: list[str] = state.context.get("topics", ["RAG", "FastAPI"])
        student_level: str = state.context.get("level", "intermediate")
        student_goal: str = state.context.get("goal", "Build production AI engineering skills")

        # ── Topic-overlap matching (deterministic, O(n)) ──────────────────────
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
            "similarity_score": min(0.95, similarity + 0.35),  # Boosted for display
            "shared_topics": best_overlap or student_topics[:2],
            "suggested_activity": "Pair code review",
            "peer_level": best_peer["level"],
            "peer_timezone": best_peer["timezone"],
            "peer_goal": best_peer["goal"],
            "student_level": student_level,
        }

        # ── LLM outreach message (Claude Sonnet) ──────────────────────────────
        connection_message: str = ""
        if settings.anthropic_api_key:
            try:
                llm = self._build_llm()
                connection_message = await self._generate_outreach(
                    llm,
                    best_peer,
                    student_topics,
                    student_goal,
                    best_overlap or student_topics[:2],
                )
            except Exception as exc:
                self._log.warning("peer_matching.llm_failed", error=str(exc))
                connection_message = (
                    f"You matched with {best_peer['name']} based on shared interest in "
                    f"{', '.join(best_overlap or student_topics[:2])}. "
                    f"Reach out and suggest a paired code review session!"
                )
        else:
            connection_message = (
                f"You matched with {best_peer['name']} based on shared interest in "
                f"{', '.join(best_overlap or student_topics[:2])}. "
                f"Reach out and suggest a paired code review session!"
            )

        match["connection_message"] = connection_message

        return state.model_copy(
            update={
                "response": json.dumps(match, indent=2),
                "context": {**state.context, "peer_match": match},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        try:
            result = json.loads(state.response or "{}")
            has_match = "matched_with" in result
            has_message = bool(result.get("connection_message", ""))
            score = 0.9 if (has_match and has_message) else (0.6 if has_match else 0.3)
        except (json.JSONDecodeError, TypeError):
            score = 0.3
        return state.model_copy(update={"evaluation_score": score})
