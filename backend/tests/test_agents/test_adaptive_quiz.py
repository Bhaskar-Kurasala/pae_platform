import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.adaptive_quiz import _SAMPLE_QUESTIONS, AdaptiveQuizAgent
from app.agents.base_agent import AgentState

SAMPLE_EVAL_RESPONSE = {
    "correct": True,
    "explanation": "RAG retrieves context to ground the LLM response.",
    "correct_answer": "B",
    "next_action": "next_question",
    "encouragement": "Great job!",
}


def _make_mock_llm(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
    return mock_llm


@pytest.mark.asyncio
async def test_adaptive_quiz_registered() -> None:
    import app.agents.adaptive_quiz  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "adaptive_quiz" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_sample_questions_exist() -> None:
    assert len(_SAMPLE_QUESTIONS) >= 3
    for q in _SAMPLE_QUESTIONS:
        assert "question" in q
        assert "options" in q
        assert "correct" in q
        assert len(q["options"]) == 4


@pytest.mark.asyncio
async def test_quiz_generates_question_from_bank() -> None:
    """First question should come from the sample bank (no LLM needed)."""
    agent = AdaptiveQuizAgent()
    state = AgentState(
        student_id="s1",
        task="quiz me",
        context={"difficulty": "beginner"},
    )

    # No LLM mock needed — should use sample bank
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")

    assert "question" in data
    assert "options" in data
    assert data["difficulty"] == "beginner"


@pytest.mark.asyncio
async def test_quiz_evaluates_correct_answer() -> None:
    """Evaluating a correct answer should update quiz_state streak."""
    agent = AdaptiveQuizAgent()
    first_q = _SAMPLE_QUESTIONS[0]
    state = AgentState(
        student_id="s1",
        task="B",
        context={
            "last_question": {"question_id": first_q["id"], "question": first_q["question"]},
            "student_answer": "B",
            "quiz_state": {
                "answered": 1,
                "correct": 0,
                "streak": 0,
                "current_difficulty": "beginner",
                "questions_asked": [first_q["id"]],
            },
        },
    )

    with patch.object(agent, "_build_llm", return_value=_make_mock_llm(json.dumps(SAMPLE_EVAL_RESPONSE))):
        result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert data["correct"] is True
    assert data["next_action"] == "next_question"


@pytest.mark.asyncio
async def test_quiz_difficulty_increases_on_streak() -> None:
    """After 3 consecutive correct answers, difficulty should increase."""
    agent = AdaptiveQuizAgent()
    first_q = _SAMPLE_QUESTIONS[0]
    state = AgentState(
        student_id="s1",
        task="B",
        context={
            "last_question": {"question_id": first_q["id"]},
            "student_answer": "B",
            "quiz_state": {
                "answered": 3,
                "correct": 2,
                "streak": 3,  # Already at 3
                "current_difficulty": "beginner",
                "questions_asked": [first_q["id"]],
            },
        },
    )

    with patch.object(agent, "_build_llm", return_value=_make_mock_llm(json.dumps(SAMPLE_EVAL_RESPONSE))):
        result = await agent.execute(state)

    # After correct answer with streak=3, difficulty should bump to intermediate
    assert result.context["quiz_state"]["current_difficulty"] == "intermediate"


@pytest.mark.asyncio
async def test_quiz_evaluation_score() -> None:
    """Valid JSON response scores 0.9, garbage scores 0.4."""
    agent = AdaptiveQuizAgent()

    good_state = AgentState(
        student_id="s1", task="q", response=json.dumps({"question": "x", "options": {}})
    )
    evaluated = await agent.evaluate(good_state)
    assert evaluated.evaluation_score == 0.9

    bad_state = AgentState(student_id="s1", task="q", response="not json at all {{{{")
    evaluated_bad = await agent.evaluate(bad_state)
    assert evaluated_bad.evaluation_score == 0.4
