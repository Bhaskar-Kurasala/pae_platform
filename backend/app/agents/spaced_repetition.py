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

_PROMPT = (Path(__file__).parent / "prompts" / "spaced_repetition.md").read_text()

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
    """Implements SM-2 spaced repetition algorithm with LLM explanations.

    The SM-2 algorithm runs deterministically (no LLM cost). When
    `last_answer_correct` is False in context, Claude Haiku generates a
    'why you got this wrong' explanation to reinforce learning.
    """

    name = "spaced_repetition"
    description = (
        "Implements SM-2 spaced repetition algorithm to schedule optimal review times. "
        "When an answer is wrong, generates a targeted 'why you got this wrong' explanation."
    )
    trigger_conditions = [
        "review",
        "flashcard",
        "spaced repetition",
        "due cards",
        "review time",
    ]
    model = "claude-haiku-4-5"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=256,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _explain_wrong_answer(
        self,
        llm: ChatAnthropic,
        question: str,
        student_answer: str,
        correct_answer: str,
        concept: str,
    ) -> str:
        """Generate a brief 'why you got this wrong' explanation."""
        messages: list[Any] = [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"The student answered a question incorrectly.\n\n"
                    f"Concept: {concept}\n"
                    f"Question: {question}\n"
                    f"Student's answer: {student_answer or 'Not provided'}\n"
                    f"Correct answer: {correct_answer or 'Not provided'}\n\n"
                    "In 2-3 concise sentences, explain:\n"
                    "1. The key misconception that likely caused the wrong answer\n"
                    "2. The correct mental model to apply for this concept\n\n"
                    "Be direct and specific — no padding."
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        return str(response.content)

    async def execute(self, state: AgentState) -> AgentState:
        card_history: list[dict[str, Any]] = state.context.get("card_history", [])
        last_answer_correct: bool | None = state.context.get("last_answer_correct")

        # ── SM-2 algorithm (deterministic, no LLM) ────────────────────────────
        interval = _DEFAULT_INTERVAL
        ease_factor = _DEFAULT_EASE_FACTOR

        for entry in card_history:
            correct: bool = bool(entry.get("correct", False))
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

        # ── LLM explanation for wrong answers (Claude Haiku — fast) ──────────
        wrong_answer_explanation: str | None = None
        if last_answer_correct is False and settings.anthropic_api_key:
            last_card = card_history[-1] if card_history else {}
            question = last_card.get("question", state.task)
            student_answer = str(last_card.get("student_answer", ""))
            correct_answer = str(last_card.get("correct_answer", ""))
            concept = last_card.get("concept", "AI Engineering")
            try:
                llm = self._build_llm()
                wrong_answer_explanation = await self._explain_wrong_answer(
                    llm, question, student_answer, correct_answer, concept
                )
            except Exception as exc:
                self._log.warning("spaced_repetition.llm_failed", error=str(exc))
                wrong_answer_explanation = (
                    f"Review the '{concept}' concept carefully. "
                    f"The key idea to focus on: make sure you understand the "
                    f"distinction between the correct answer and your response."
                )

        if wrong_answer_explanation:
            schedule["wrong_answer_explanation"] = wrong_answer_explanation

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
