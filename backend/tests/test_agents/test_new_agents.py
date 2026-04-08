"""Tests for all Phase 4 agents (one test per agent, mock LLM where needed)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base_agent import AgentState


def _mock_llm(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=resp)
    return llm


# ── Creation Agents ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_ingestion_youtube_stub() -> None:
    from app.agents.content_ingestion import ContentIngestionAgent

    agent = ContentIngestionAgent()
    state = AgentState(
        student_id="s1",
        task="ingest video",
        context={"url": "https://www.youtube.com/watch?v=abc123"},
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    assert "title" in data or "source_type" in data


@pytest.mark.asyncio
async def test_curriculum_mapper_calls_llm() -> None:
    from app.agents.curriculum_mapper import CurriculumMapperAgent

    agent = CurriculumMapperAgent()
    state = AgentState(
        student_id="s1",
        task="map curriculum",
        context={"content_metadata": {"topics": ["RAG", "LangGraph"], "title": "Advanced RAG"}},
    )
    llm_response = json.dumps({"suggested_position": "after lesson 3", "topics_covered": ["RAG"], "prerequisites": []})
    with patch.object(agent, "_build_llm", return_value=_mock_llm(llm_response)):
        result = await agent.execute(state)
    assert result.response is not None


@pytest.mark.asyncio
async def test_mcq_factory_generates_questions() -> None:
    from app.agents.mcq_factory import MCQFactoryAgent

    agent = MCQFactoryAgent()
    state = AgentState(student_id="s1", task="generate questions about RAG")
    mock_mcqs = json.dumps([
        {
            "question": "What does RAG stand for?",
            "options": {"A": "Retrieval Augmented Generation", "B": "Random Agent Graph", "C": "Recurrent Agent Grid", "D": "Real-time API Gateway"},
            "correct_answer": "A",
            "explanation": "RAG = Retrieval Augmented Generation",
            "difficulty": "beginner",
            "tags": ["RAG"],
        }
    ])
    with patch.object(agent, "_build_llm", return_value=_mock_llm(mock_mcqs)):
        result = await agent.execute(state)
    evaluated = await agent.evaluate(result)
    assert evaluated.evaluation_score == 0.9
    data = json.loads(result.response or "[]")
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_coding_assistant_returns_markdown() -> None:
    from app.agents.coding_assistant import CodingAssistantAgent

    agent = CodingAssistantAgent()
    state = AgentState(
        student_id="s1",
        task="help with code",
        context={"code": "def add(a, b):\n    return a + b"},
    )
    with patch.object(agent, "_build_llm", return_value=_mock_llm(
        "Nice work! A few suggestions:\n\n**Line 1**: Add type hints → `def add(a: int, b: int) -> int:`"
    )):
        result = await agent.execute(state)
    assert result.response is not None


@pytest.mark.asyncio
async def test_student_buddy_short_response() -> None:
    from app.agents.student_buddy import StudentBuddyAgent

    agent = StudentBuddyAgent()
    state = AgentState(student_id="s1", task="tldr what is RAG?")
    short_resp = "RAG = Retrieval Augmented Generation. It fetches relevant docs from a vector DB and injects them as context before asking the LLM your question. Solves knowledge cutoff and hallucination."
    with patch.object(agent, "_build_llm", return_value=_mock_llm(short_resp)):
        result = await agent.execute(state)
    assert result.response is not None
    assert len(result.response) < 500  # Should be short


@pytest.mark.asyncio
async def test_deep_capturer_stub() -> None:
    from app.agents.deep_capturer import DeepCapturerAgent

    agent = DeepCapturerAgent()
    state = AgentState(student_id="s1", task="weekly summary")
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    assert "week_theme" in data or "connections" in data


# ── Learning Agents ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spaced_repetition_sm2_correct() -> None:
    from app.agents.spaced_repetition import SpacedRepetitionAgent

    agent = SpacedRepetitionAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={
            "card_history": [
                {"correct": True, "interval_days": 1, "ease_factor": 2.5},
            ]
        },
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    # After correct answer: interval should increase
    assert data["next_review_in_days"] > 1


@pytest.mark.asyncio
async def test_spaced_repetition_sm2_wrong() -> None:
    from app.agents.spaced_repetition import SpacedRepetitionAgent

    agent = SpacedRepetitionAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={
            "card_history": [
                {"correct": False, "interval_days": 7, "ease_factor": 2.5},
            ]
        },
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    # After wrong answer: interval resets to 1
    assert data["next_review_in_days"] == 1


@pytest.mark.asyncio
async def test_knowledge_graph_stub() -> None:
    from app.agents.knowledge_graph import KnowledgeGraphAgent

    agent = KnowledgeGraphAgent()
    state = AgentState(
        student_id="s1",
        task="update knowledge",
        context={"completed_topic": "RAG", "score": 0.9},
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    assert "updated_concepts" in data


@pytest.mark.asyncio
async def test_adaptive_path_calls_llm() -> None:
    from app.agents.adaptive_path import AdaptivePathAgent

    agent = AdaptivePathAgent()
    state = AgentState(
        student_id="s1",
        task="what should I study next?",
        context={"quiz_scores": {"RAG": 0.9, "LangGraph": 0.4}},
    )
    path_resp = json.dumps({"next_topic": "LangGraph", "reason": "Low score of 0.4", "skip": ["RAG"]})
    with patch.object(agent, "_build_llm", return_value=_mock_llm(path_resp)):
        result = await agent.execute(state)
    assert result.response is not None


# ── Analytics Agents ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_project_evaluator_scores() -> None:
    from app.agents.project_evaluator import ProjectEvaluatorAgent

    agent = ProjectEvaluatorAgent()
    state = AgentState(
        student_id="s1",
        task="evaluate my capstone",
        context={"submission": "Built a RAG pipeline...", "rubric": {"correctness": 20}},
    )
    eval_resp = json.dumps({"score": 82, "summary": "Solid work.", "approved": True, "feedback": {}})
    with patch.object(agent, "_build_llm", return_value=_mock_llm(eval_resp)):
        result = await agent.execute(state)
    evaluated = await agent.evaluate(result)
    assert evaluated.evaluation_score == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_progress_report_generates_text() -> None:
    from app.agents.progress_report import ProgressReportAgent

    agent = ProgressReportAgent()
    state = AgentState(
        student_id="s1",
        task="how am I doing?",
        context={"lessons_completed": 5, "quiz_avg": 0.75},
    )
    with patch.object(agent, "_build_llm", return_value=_mock_llm(
        "Great week! You completed 5 lessons and scored 75% on quizzes."
    )):
        result = await agent.execute(state)
    assert result.response is not None


# ── Career Agents ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_interview_asks_question() -> None:
    from app.agents.mock_interview import MockInterviewAgent

    agent = MockInterviewAgent()
    state = AgentState(student_id="s1", task="start interview")
    with patch.object(agent, "_build_llm", return_value=_mock_llm(
        "Let's begin. Design a production RAG pipeline for a customer support chatbot. How would you handle document ingestion?"
    )):
        result = await agent.execute(state)
    evaluated = await agent.evaluate(result)
    assert evaluated.evaluation_score == 0.9  # Contains "?"


@pytest.mark.asyncio
async def test_portfolio_builder_returns_markdown() -> None:
    from app.agents.portfolio_builder import PortfolioBuilderAgent

    agent = PortfolioBuilderAgent()
    state = AgentState(
        student_id="s1",
        task="build my portfolio",
        context={"projects": [{"name": "RAG Pipeline", "description": "Built a production RAG system"}]},
    )
    with patch.object(agent, "_build_llm", return_value=_mock_llm(
        "# RAG Pipeline\n\n## Overview\nBuilt a production-grade RAG system using LangGraph and Pinecone "
        "that handles real-time document retrieval, chunking, embedding, and LLM-powered answer generation. "
        "Deployed to production with 99.9% uptime.\n\n## Tech Stack\n- LangGraph, Pinecone, FastAPI, Claude"
    )):
        result = await agent.execute(state)
    evaluated = await agent.evaluate(result)
    assert evaluated.evaluation_score == 0.9  # Has "# " heading


@pytest.mark.asyncio
async def test_job_match_returns_listings() -> None:
    from app.agents.job_match import JobMatchAgent

    agent = JobMatchAgent()
    state = AgentState(
        student_id="s1",
        task="find jobs",
        context={"skills": ["LangGraph", "RAG", "FastAPI"]},
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "[]")
    assert isinstance(data, list)
    assert len(data) > 0
    assert "title" in data[0]


# ── Engagement Agents ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disrupt_prevention_active_user_no_action() -> None:
    from app.agents.disrupt_prevention import DisruptPreventionAgent

    agent = DisruptPreventionAgent()
    state = AgentState(
        student_id="s1",
        task="check engagement",
        context={"days_inactive": 1},
    )
    result = await agent.execute(state)
    # Less than 3 days inactive — should return no-action response
    data = json.loads(result.response or "{}")
    # Agent signals no action needed via action="none" or action_needed=False
    no_action = data.get("action") == "none" or data.get("action_needed") is False
    assert no_action, f"Expected no-action response, got: {data}"


@pytest.mark.asyncio
async def test_disrupt_prevention_inactive_user_sends_message() -> None:
    from app.agents.disrupt_prevention import DisruptPreventionAgent

    agent = DisruptPreventionAgent()
    state = AgentState(
        student_id="s1",
        task="check engagement",
        context={"days_inactive": 7},
    )
    with patch.object(agent, "_build_llm", return_value=_mock_llm(
        "Hey! We miss you. You were making great progress on RAG. Come back and keep going!"
    )):
        result = await agent.execute(state)
    assert result.response is not None


@pytest.mark.asyncio
async def test_peer_matching_stub() -> None:
    from app.agents.peer_matching import PeerMatchingAgent

    agent = PeerMatchingAgent()
    state = AgentState(
        student_id="s1",
        task="find study partner",
        context={"topics": ["RAG", "FastAPI"]},
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    assert "matched_with" in data or "similarity_score" in data


@pytest.mark.asyncio
async def test_community_celebrator_generates_message() -> None:
    from app.agents.community_celebrator import CommunityCelebratorAgent

    agent = CommunityCelebratorAgent()
    state = AgentState(
        student_id="s1",
        task="celebrate",
        context={"milestone": "Completed the LangGraph course!"},
    )
    with patch.object(agent, "_build_llm", return_value=_mock_llm(
        "🎉 Huge congratulations on completing the LangGraph course! You're now in the top 10% of our learners!"
    )):
        result = await agent.execute(state)
    assert result.response is not None


# ── Registry completeness ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_agents_registered() -> None:
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered

    _ensure_registered()
    expected = [
        "adaptive_path", "adaptive_quiz", "code_review", "coding_assistant",
        "community_celebrator", "content_ingestion", "curriculum_mapper", "deep_capturer",
        "disrupt_prevention", "job_match", "knowledge_graph", "mcq_factory",
        "mock_interview", "peer_matching", "portfolio_builder", "progress_report",
        "project_evaluator", "socratic_tutor", "spaced_repetition", "student_buddy",
    ]
    for name in expected:
        assert name in AGENT_REGISTRY, f"Agent '{name}' not in registry"


@pytest.mark.asyncio
async def test_moa_keyword_routing() -> None:
    """MOA keyword router should correctly classify common patterns."""
    from app.agents.moa import _keyword_route

    assert _keyword_route("review my code") == "code_review"
    assert _keyword_route("quiz me on RAG") == "adaptive_quiz"
    assert _keyword_route("mock interview please") == "mock_interview"
    assert _keyword_route("find jobs in AI") == "job_match"
    assert _keyword_route("find peer to study with") == "peer_matching"
    # Should return None for unknown intent (falls back to LLM)
    assert _keyword_route("hello") is None
