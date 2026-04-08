import json
import uuid
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

_PROMPT = (Path(__file__).parent / "prompts" / "adaptive_quiz.md").read_text()

# Sample MCQ bank used when database is unavailable (tests / early dev)
_SAMPLE_QUESTIONS = [
    {
        "id": str(uuid.uuid4()),
        "question": "What problem does RAG (Retrieval Augmented Generation) primarily solve?",
        "options": {
            "A": "Makes LLMs run faster",
            "B": "Grounds LLM responses in retrieved, up-to-date context",
            "C": "Reduces the cost of LLM API calls",
            "D": "Enables LLMs to write code",
        },
        "correct": "B",
        "difficulty": "beginner",
        "concept": "RAG",
        "explanation": "RAG retrieves relevant documents and injects them as context, addressing knowledge cutoff and hallucination issues.",
    },
    {
        "id": str(uuid.uuid4()),
        "question": "In LangGraph, what is the purpose of a 'conditional edge'?",
        "options": {
            "A": "To define the starting node of a graph",
            "B": "To route execution to different nodes based on state",
            "C": "To create parallel branches that always run",
            "D": "To terminate the graph execution",
        },
        "correct": "B",
        "difficulty": "intermediate",
        "concept": "LangGraph",
        "explanation": "Conditional edges examine the current state and route to different nodes based on custom logic, enabling dynamic agent workflows.",
    },
    {
        "id": str(uuid.uuid4()),
        "question": "Which Pydantic feature ensures LLM output is validated before use in production?",
        "options": {
            "A": "model_dump()",
            "B": "model_validate() with strict=True",
            "C": "BaseModel inheritance alone",
            "D": "Field(default=None)",
        },
        "correct": "B",
        "difficulty": "intermediate",
        "concept": "Pydantic v2",
        "explanation": "model_validate() with strict=True raises ValidationError on any type mismatch, preventing bad LLM output from corrupting downstream logic.",
    },
]


@register
class AdaptiveQuizAgent(BaseAgent):
    name = "adaptive_quiz"
    description = "Runs adaptive MCQ quizzes, adjusting difficulty based on student performance in real-time."
    trigger_conditions = [
        "quiz me",
        "test my knowledge",
        "start quiz",
        "practice questions",
        "MCQ",
        "multiple choice",
    ]
    model = "claude-sonnet-4-6"

    def _build_llm(self) -> ChatAnthropic:
        return ChatAnthropic(  # type: ignore[call-arg]
            model=self.model,
            anthropic_api_key=SecretStr(settings.anthropic_api_key) if settings.anthropic_api_key else None,
            max_tokens=1024,
        )

    def _get_quiz_state(self, state: AgentState) -> dict[str, Any]:
        return state.context.get(
            "quiz_state",
            {
                "answered": 0,
                "correct": 0,
                "streak": 0,
                "current_difficulty": state.context.get("difficulty", "beginner"),
                "questions_asked": [],
            },
        )

    async def execute(self, state: AgentState) -> AgentState:
        quiz_state = self._get_quiz_state(state)

        # Determine mode: generating question or evaluating an answer
        last_question = state.context.get("last_question")
        student_answer = state.context.get("student_answer")

        mode = "evaluate" if last_question and student_answer else "generate"

        if mode == "generate":
            # Pick a sample question matching current difficulty, or use LLM
            difficulty = quiz_state["current_difficulty"]
            candidates = [
                q for q in _SAMPLE_QUESTIONS
                if q["difficulty"] == difficulty
                and q["id"] not in quiz_state["questions_asked"]
            ]

            if candidates:
                q = candidates[0]
                quiz_state["questions_asked"].append(q["id"])
                quiz_state["answered"] += 1
                response_data: dict[str, Any] = {
                    "question_id": q["id"],
                    "question": q["question"],
                    "options": q["options"],
                    "difficulty": q["difficulty"],
                    "concept": q["concept"],
                }
                response_str = json.dumps(response_data, indent=2)
            else:
                # Generate a new question via LLM
                llm = self._build_llm()
                messages: list[Any] = [
                    SystemMessage(content=_PROMPT),
                    HumanMessage(
                        content=(
                            f"Generate a {difficulty} difficulty question about production AI engineering. "
                            f"Topics the student has covered: {state.context.get('topics', 'RAG, LangGraph, FastAPI')}. "
                            "Return JSON matching the question schema from your system prompt."
                        )
                    ),
                ]
                resp = await llm.ainvoke(messages)
                response_str = str(resp.content)

        else:  # evaluate mode
            llm = self._build_llm()
            difficulty = quiz_state["current_difficulty"]
            q_data = last_question or {}
            correct_answer = next(
                (q["correct"] for q in _SAMPLE_QUESTIONS if q["id"] == q_data.get("question_id")),
                None,
            )
            messages = [
                SystemMessage(content=_PROMPT),
                HumanMessage(
                    content=(
                        f"The student was asked: {json.dumps(q_data)}\n\n"
                        f"Their answer: {student_answer}\n"
                        f"Correct answer: {correct_answer or 'Unknown — use your judgment'}\n\n"
                        "Evaluate and return JSON matching the evaluation schema from your system prompt."
                    )
                ),
            ]
            resp = await llm.ainvoke(messages)
            eval_raw = str(resp.content)

            try:
                if "```json" in eval_raw:
                    eval_raw = eval_raw.split("```json")[1].split("```")[0].strip()
                eval_data = json.loads(eval_raw)
                if eval_data.get("correct"):
                    quiz_state["correct"] += 1
                    quiz_state["streak"] += 1
                    if quiz_state["streak"] >= 3 and difficulty != "advanced":
                        quiz_state["current_difficulty"] = (
                            "advanced" if difficulty == "intermediate" else "intermediate"
                        )
                else:
                    quiz_state["streak"] = 0
                    if difficulty != "beginner":
                        quiz_state["current_difficulty"] = (
                            "beginner" if difficulty == "intermediate" else "intermediate"
                        )
                response_str = json.dumps(eval_data, indent=2)
            except (json.JSONDecodeError, KeyError):
                response_str = eval_raw

        updated_context = {
            **state.context,
            "quiz_state": quiz_state,
            "last_question": state.context.get("last_question"),
        }

        return state.model_copy(
            update={"response": response_str, "context": updated_context}
        )

    async def evaluate(self, state: AgentState) -> AgentState:
        """Valid if response is parseable JSON."""
        try:
            raw = state.response or ""
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            json.loads(raw)
            score = 0.9
        except json.JSONDecodeError:
            score = 0.4
        return state.model_copy(update={"evaluation_score": score})
