import json
from pathlib import Path
from typing import Any

import structlog

from app.agents.base_agent import AgentState, BaseAgent
from app.agents.registry import register

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent / "prompts" / "spaced_repetition.md"

# Mock MCQ bank for due card sampling
_MOCK_MCQ_BANK = [
    {"id": "mcq-001", "question": "What is RAG?", "concept": "RAG", "difficulty": "beginner"},
    {"id": "mcq-002", "question": "What is a LangGraph conditional edge?", "concept": "LangGraph", "difficulty": "intermediate"},
    {"id": "mcq-003", "question": "How does Pydantic model_validate() enforce type safety?", "concept": "Pydantic v2", "difficulty": "intermediate"},
    {"id": "mcq-004", "question": "What is the purpose of a vector embedding?", "concept": "Embeddings", "difficulty": "beginner"},
    {"id": "mcq-005", "question": "When should you use async def in FastAPI?", "concept": "FastAPI", "difficulty": "beginner"},
]

_DEFAULT_EASE_FACTOR = 2.5
_DEFAULT_INTERVAL = 1


def _apply_sm2(
    correct: bool,
    interval_days: int,
    ease_factor: float,
) -> tuple[int, float]:
    """Apply one SM-2 step. Returns (next_interval_days, new_ease_factor)."""
    if correct:
        new_interval = max(1, round(interval_days * ease_factor))
        new_ease = min(3.0, ease_factor + 0.1)
    else:
        new_interval = 1
        new_ease = max(1.3, ease_factor - 0.2)
    return new_interval, new_ease


@register
class SpacedRepetitionAgent(BaseAgent):
    name = "spaced_repetition"
    description = "Implements SM-2 spaced repetition algorithm to schedule optimal review times for each student."
    trigger_conditions = [
        "review",
        "flashcard",
        "spaced repetition",
        "due cards",
        "review time",
    ]
    model = "claude-sonnet-4-6"

    async def execute(self, state: AgentState) -> AgentState:
        card_history: list[dict[str, Any]] = state.context.get("card_history", [])

        # Aggregate SM-2 across all historical answers
        interval = _DEFAULT_INTERVAL
        ease_factor = _DEFAULT_EASE_FACTOR

        for entry in card_history:
            correct: bool = bool(entry.get("correct", False))
            # Use the stored interval if available, otherwise carry forward
            prev_interval: int = int(entry.get("interval_days", interval))
            prev_ease: float = float(entry.get("ease_factor", ease_factor))
            interval, ease_factor = _apply_sm2(correct, prev_interval, prev_ease)

        # Sample due cards from mock bank (Phase 4: query real DB)
        due_cards: list[dict[str, Any]] = _MOCK_MCQ_BANK[:3]

        schedule: dict[str, Any] = {
            "next_review_in_days": interval,
            "ease_factor": round(ease_factor, 3),
            "interval_days": interval,
            "due_cards": due_cards,
            "cards_reviewed": len(card_history),
        }

        return state.model_copy(
            update={
                "response": json.dumps(schedule, indent=2),
                "context": {**state.context, "review_schedule": schedule},
            }
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        try:
            schedule = json.loads(state.response or "{}")
            has_interval = "next_review_in_days" in schedule
            score = 0.9 if has_interval else 0.4
        except (json.JSONDecodeError, TypeError):
            score = 0.3
        return state.model_copy(update={"evaluation_score": score})
