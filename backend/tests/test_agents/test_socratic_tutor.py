from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base_agent import AgentState
from app.agents.socratic_tutor import SocraticTutorAgent


def _make_mock_llm(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
    return mock_llm


@pytest.mark.asyncio
async def test_socratic_tutor_registered() -> None:
    # Importing the module triggers registration
    import app.agents.socratic_tutor  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "socratic_tutor" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_socratic_tutor_has_question_mark() -> None:
    """A good Socratic response must contain a question mark."""
    agent = SocraticTutorAgent()
    state = AgentState(student_id="s1", task="What is RAG?")

    with patch.object(agent, "_build_llm", return_value=_make_mock_llm(
        "Great question! What do you think happens when an LLM doesn't have access to current data? "
        "And how might you solve that problem?"
    )):
        result = await agent.execute(state)

    assert result.response is not None
    assert "?" in result.response


@pytest.mark.asyncio
async def test_socratic_tutor_evaluation_passes_with_question() -> None:
    agent = SocraticTutorAgent()
    state = AgentState(
        student_id="s1",
        task="explain RAG",
        response="What do you think? How would you retrieve context?",
    )
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == 0.9


@pytest.mark.asyncio
async def test_socratic_tutor_evaluation_fails_without_question() -> None:
    agent = SocraticTutorAgent()
    state = AgentState(
        student_id="s1",
        task="explain RAG",
        response="RAG stands for Retrieval Augmented Generation.",
    )
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == 0.3


@pytest.mark.asyncio
async def test_socratic_tutor_uses_search_tool() -> None:
    """Socratic tutor should call search_course_content and add it to tools_used."""
    agent = SocraticTutorAgent()
    state = AgentState(student_id="s1", task="What is RAG?")

    with patch.object(agent, "_build_llm", return_value=_make_mock_llm(
        "What problem do you think an LLM faces with recent events?"
    )):
        result = await agent.execute(state)

    assert "search_course_content" in result.tools_used


@pytest.mark.asyncio
async def test_socratic_tutor_full_run() -> None:
    """Full run pipeline produces a scored result with the agent name set."""
    agent = SocraticTutorAgent()
    state = AgentState(student_id="s1", task="How does LangGraph work?")

    with patch.object(agent, "_build_llm", return_value=_make_mock_llm(
        "Interesting! What do you think a 'graph' in software usually represents? "
        "And why might that be useful for chaining AI agents?"
    )):
        result = await agent.run(state)

    assert result.agent_name == "socratic_tutor"
    assert result.evaluation_score == 0.9
    assert result.response is not None
