"""Tests for WS4 agent implementations.

Covers:
- knowledge_graph (enhanced with LLM narrative)
- peer_matching (enhanced with connection message)
- deep_capturer (real Claude Sonnet synthesis)
- spaced_repetition (wrong-answer LLM explanation)
- content_ingestion (GitHub/YouTube/text routing)
- career_coach (new agent)
- resume_reviewer (new agent)
- billing_support (new agent + guardrail)
- RagService
- stream and demo route basics
"""

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


# ── knowledge_graph ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_graph_registered() -> None:
    import app.agents.knowledge_graph  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "knowledge_graph" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_knowledge_graph_ema_update() -> None:
    from app.agents.knowledge_graph import KnowledgeGraphAgent

    agent = KnowledgeGraphAgent()
    state = AgentState(
        student_id="s1",
        task="update knowledge",
        context={
            "quiz_scores": {"RAG": 0.9, "LangGraph": 0.5},
            "concept_mastery": {"RAG": 0.7, "LangGraph": 0.6},
        },
    )
    narrative = "Your RAG mastery is strong. Focus on LangGraph and Pinecone gaps.\n1. Study conditional edges.\n2. Build a retrieval node.\n3. Write evaluation metrics."
    with patch("app.agents.knowledge_graph.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm(narrative)):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert "updated_concepts" in data
    # RAG: 0.7 * 0.9 + 0.3 * 0.7 = 0.63 + 0.21 = 0.84
    assert data["updated_concepts"]["RAG"] == pytest.approx(0.84, abs=0.01)
    assert "explanation" in data
    assert data["explanation"] == narrative


@pytest.mark.asyncio
async def test_knowledge_graph_fallback_mastery() -> None:
    """No quiz scores → use fallback mock mastery."""
    from app.agents.knowledge_graph import KnowledgeGraphAgent

    agent = KnowledgeGraphAgent()
    state = AgentState(student_id="s1", task="skill map")
    with patch.object(agent, "_build_llm", return_value=_mock_llm("Focus on LangGraph gaps.")):
        result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert "RAG" in data["updated_concepts"]


@pytest.mark.asyncio
async def test_knowledge_graph_llm_failure_graceful() -> None:
    """LLM failure should not crash — fallback explanation used."""
    from app.agents.knowledge_graph import KnowledgeGraphAgent

    agent = KnowledgeGraphAgent()
    state = AgentState(
        student_id="s1",
        task="update knowledge",
        context={"quiz_scores": {"RAG": 0.8}},
    )
    with patch("app.agents.knowledge_graph.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_call_llm", side_effect=Exception("LLM down")):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert "explanation" in data
    assert data["explanation"]  # fallback text present


@pytest.mark.asyncio
async def test_knowledge_graph_evaluate() -> None:
    from app.agents.knowledge_graph import KnowledgeGraphAgent

    agent = KnowledgeGraphAgent()
    state_good = AgentState(
        student_id="s1",
        task="skill map",
        response=json.dumps({"updated_concepts": {"RAG": 0.9}, "explanation": "Great progress!"}),
    )
    evaluated = await agent.evaluate(state_good)
    assert evaluated.evaluation_score == pytest.approx(0.9)

    state_no_explain = AgentState(
        student_id="s1",
        task="skill map",
        response=json.dumps({"updated_concepts": {"RAG": 0.9}, "explanation": ""}),
    )
    evaluated2 = await agent.evaluate(state_no_explain)
    assert evaluated2.evaluation_score == pytest.approx(0.6)


# ── peer_matching ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_peer_matching_registered() -> None:
    import app.agents.peer_matching  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "peer_matching" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_peer_matching_generates_connection_message() -> None:
    from app.agents.peer_matching import PeerMatchingAgent

    agent = PeerMatchingAgent()
    state = AgentState(
        student_id="s1",
        task="find study partner",
        context={"topics": ["RAG", "FastAPI"], "goal": "Build production AI apps"},
    )
    message = "Great match! You both love RAG and FastAPI. Reach out and suggest a code review."
    with patch("app.agents.peer_matching.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm(message)):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert "matched_with" in data
    assert "connection_message" in data
    assert data["connection_message"] == message


@pytest.mark.asyncio
async def test_peer_matching_topic_overlap_scoring() -> None:
    from app.agents.peer_matching import PeerMatchingAgent

    agent = PeerMatchingAgent()
    # Topics that match Jordan Lee ("LangGraph", "Pinecone", "LLM evaluation")
    state = AgentState(
        student_id="s1",
        task="find peers",
        context={"topics": ["LangGraph", "Pinecone", "LLM evaluation"]},
    )
    with patch("app.agents.peer_matching.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm("You match with Jordan!")):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert data["matched_with"] == "Jordan Lee"


@pytest.mark.asyncio
async def test_peer_matching_llm_failure_fallback() -> None:
    from app.agents.peer_matching import PeerMatchingAgent

    agent = PeerMatchingAgent()
    state = AgentState(
        student_id="s1",
        task="find study partner",
        context={"topics": ["RAG"]},
    )
    with patch("app.agents.peer_matching.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_generate_outreach", side_effect=Exception("LLM down")):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert "connection_message" in data
    assert data["connection_message"]  # fallback text present


# ── deep_capturer ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deep_capturer_registered() -> None:
    import app.agents.deep_capturer  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "deep_capturer" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_deep_capturer_llm_synthesis() -> None:
    from app.agents.deep_capturer import DeepCapturerAgent

    agent = DeepCapturerAgent()
    state = AgentState(
        student_id="s1",
        task="weekly summary",
        context={
            "lessons_completed": ["RAG Basics", "LangGraph State"],
            "concepts_seen": ["RAG", "LangGraph", "Pydantic v2"],
            "week_theme": "Stateful AI Orchestration",
        },
    )
    synthesis = (
        "## Concept Connections\n\n"
        "RAG and LangGraph both depend on reliable state management.\n\n"
        "## Surprise Connection\n\n"
        "RAG retrieval is itself a LangGraph node — same pattern, different scale.\n\n"
        "## Sticky Metaphor\n\n"
        "Think of AgentState as a relay baton that every node must pass cleanly."
    )
    with patch("app.agents.deep_capturer.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm(synthesis)):
            result = await agent.execute(state)

    assert result.response == synthesis
    assert "weekly_synthesis" in result.context


@pytest.mark.asyncio
async def test_deep_capturer_fallback_synthesis() -> None:
    """No LLM key → fallback synthesis still has required sections."""
    from app.agents.deep_capturer import DeepCapturerAgent

    agent = DeepCapturerAgent()
    state = AgentState(
        student_id="s1",
        task="big picture",
        context={"concepts_seen": ["RAG", "LangGraph"]},
    )
    with patch("app.agents.deep_capturer.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        result = await agent.execute(state)

    assert "## Concept Connections" in (result.response or "")
    assert "## Sticky Metaphor" in (result.response or "")


@pytest.mark.asyncio
async def test_deep_capturer_evaluate() -> None:
    from app.agents.deep_capturer import DeepCapturerAgent

    agent = DeepCapturerAgent()
    good_state = AgentState(
        student_id="s1",
        task="synthesis",
        response="## Concept Connections\n...\n## Sticky Metaphor\nLike a relay race.",
    )
    evaluated = await agent.evaluate(good_state)
    assert evaluated.evaluation_score == pytest.approx(0.9)


# ── spaced_repetition ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spaced_repetition_registered() -> None:
    import app.agents.spaced_repetition  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "spaced_repetition" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_spaced_repetition_sm2_correct_no_explanation() -> None:
    """Correct answer → no LLM explanation generated."""
    from app.agents.spaced_repetition import SpacedRepetitionAgent

    agent = SpacedRepetitionAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={
            "card_history": [{"correct": True, "interval_days": 1, "ease_factor": 2.5}],
            "last_answer_correct": True,
        },
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    assert data["next_review_in_days"] > 1
    assert "wrong_answer_explanation" not in data


@pytest.mark.asyncio
async def test_spaced_repetition_wrong_answer_explanation() -> None:
    """Wrong answer → LLM explanation injected into response."""
    from app.agents.spaced_repetition import SpacedRepetitionAgent

    agent = SpacedRepetitionAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={
            "card_history": [
                {
                    "correct": False,
                    "interval_days": 7,
                    "ease_factor": 2.5,
                    "question": "What is a LangGraph conditional edge?",
                    "student_answer": "A loop",
                    "correct_answer": "A function that returns the next node name based on state",
                    "concept": "LangGraph",
                }
            ],
            "last_answer_correct": False,
        },
    )
    explanation = "The key misconception is confusing edges with loops. A conditional edge is a routing function, not iteration."
    with patch("app.agents.spaced_repetition.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm(explanation)):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert data["next_review_in_days"] == 1  # reset after wrong answer
    assert data["wrong_answer_explanation"] == explanation


@pytest.mark.asyncio
async def test_spaced_repetition_wrong_answer_llm_failure_fallback() -> None:
    from app.agents.spaced_repetition import SpacedRepetitionAgent

    agent = SpacedRepetitionAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={
            "card_history": [{"correct": False, "interval_days": 3, "ease_factor": 2.0, "concept": "RAG"}],
            "last_answer_correct": False,
        },
    )
    with patch("app.agents.spaced_repetition.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_explain_wrong_answer", side_effect=Exception("LLM down")):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert "wrong_answer_explanation" in data
    assert "RAG" in data["wrong_answer_explanation"]


# ── content_ingestion ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_ingestion_registered() -> None:
    import app.agents.content_ingestion  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "content_ingestion" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_content_ingestion_youtube_queued() -> None:
    from app.agents.content_ingestion import ContentIngestionAgent

    agent = ContentIngestionAgent()
    state = AgentState(
        student_id="s1",
        task="ingest video",
        context={"url": "https://www.youtube.com/watch?v=abc123"},
    )
    result = await agent.execute(state)
    data = json.loads(result.response or "{}")
    assert data["source_type"] == "youtube_video"
    assert data["status"] == "queued_phase6"
    assert "phase6_note" in data


@pytest.mark.asyncio
async def test_content_ingestion_github_no_token_summarises() -> None:
    """Without GitHub token, should still attempt LLM summarisation on fallback text."""
    from app.agents.content_ingestion import ContentIngestionAgent

    agent = ContentIngestionAgent()
    state = AgentState(
        student_id="s1",
        task="ingest repo",
        context={"url": "https://github.com/langchain-ai/langchain"},
    )
    summary_json = '{"title": "LangChain Framework", "topics": ["LangChain", "LLM"], "summary": "Core framework.", "lesson_category": "Agent Architecture", "difficulty": "intermediate"}'
    with patch("app.agents.content_ingestion.settings") as mock_settings:
        mock_settings.github_token = ""
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm(summary_json)):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert data["source_type"] == "github_repo"
    # Without token, no content parts — so LLM not called; checks fallback
    assert "title" in data


@pytest.mark.asyncio
async def test_content_ingestion_text_summarise() -> None:
    from app.agents.content_ingestion import ContentIngestionAgent

    agent = ContentIngestionAgent()
    state = AgentState(
        student_id="s1",
        task="This is a tutorial about building RAG pipelines with Pinecone and FastAPI.",
    )
    summary_json = '{"title": "RAG Tutorial", "topics": ["RAG", "Pinecone", "FastAPI"], "summary": "Building RAG.", "lesson_category": "RAG", "difficulty": "intermediate"}'
    with patch("app.agents.content_ingestion.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        mock_settings.github_token = ""
        with patch.object(agent, "_build_llm", return_value=_mock_llm(summary_json)):
            result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert data["source_type"] == "text"
    assert "topics" in data


@pytest.mark.asyncio
async def test_content_ingestion_text_no_api_key() -> None:
    from app.agents.content_ingestion import ContentIngestionAgent

    agent = ContentIngestionAgent()
    state = AgentState(student_id="s1", task="Some text about AI")
    with patch("app.agents.content_ingestion.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.github_token = ""
        result = await agent.execute(state)

    data = json.loads(result.response or "{}")
    assert "title" in data
    assert "status" in data


# ── career_coach ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_career_coach_registered() -> None:
    import app.agents.career_coach  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "career_coach" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_career_coach_generates_action_plan() -> None:
    from app.agents.career_coach import CareerCoachAgent

    agent = CareerCoachAgent()
    state = AgentState(
        student_id="s1",
        task="I want to become an AI engineer",
        context={
            "current_role": "Backend Developer",
            "target_role": "Senior AI Engineer",
            "skills": ["Python", "FastAPI", "SQL"],
            "timeline_months": 6,
        },
    )
    plan = (
        "1. Week 1-2: Audit your Python skills against AI engineering requirements.\n"
        "2. Week 3-6: Complete LangGraph and RAG modules.\n"
        "3. Week 7-10: Build production portfolio project.\n\n"
        "Top 3 skill gaps:\n1. LangGraph\n2. Vector databases\n3. LLM evaluation\n\n"
        "Portfolio projects:\n1. RAG pipeline\n2. Multi-agent system\n3. LLM eval harness"
    )
    with patch("app.agents.career_coach.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm(plan)):
            result = await agent.execute(state)

    assert result.response == plan


@pytest.mark.asyncio
async def test_career_coach_evaluate_numbered_plan() -> None:
    from app.agents.career_coach import CareerCoachAgent

    agent = CareerCoachAgent()
    state = AgentState(
        student_id="s1",
        task="career plan",
        response="1. Start with LangGraph. 2. Build RAG pipeline.\n\nSkill gaps: LLM evaluation.",
    )
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_career_coach_evaluate_no_plan() -> None:
    from app.agents.career_coach import CareerCoachAgent

    agent = CareerCoachAgent()
    state = AgentState(
        student_id="s1",
        task="career plan",
        response="You should learn AI.",
    )
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_career_coach_fallback_no_api_key() -> None:
    from app.agents.career_coach import CareerCoachAgent

    agent = CareerCoachAgent()
    state = AgentState(
        student_id="s1",
        task="career transition to AI",
        context={"current_role": "Data Analyst", "target_role": "AI Engineer"},
    )
    with patch("app.agents.career_coach.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        result = await agent.execute(state)

    assert result.response is not None
    assert "90-Day Action Plan" in (result.response or "")


# ── resume_reviewer ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_reviewer_registered() -> None:
    import app.agents.resume_reviewer  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "resume_reviewer" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_resume_reviewer_asks_for_resume_when_missing() -> None:
    from app.agents.resume_reviewer import ResumeReviewerAgent

    agent = ResumeReviewerAgent()
    state = AgentState(student_id="s1", task="review my resume", context={})
    result = await agent.execute(state)
    assert "resume" in (result.response or "").lower()


@pytest.mark.asyncio
async def test_resume_reviewer_returns_score_and_improvements() -> None:
    from app.agents.resume_reviewer import ResumeReviewerAgent

    agent = ResumeReviewerAgent()
    state = AgentState(
        student_id="s1",
        task="review my resume",
        context={"resume_text": "John Doe\nPython developer\nWorked on machine learning projects."},
    )
    review = (
        "## Overall Score: 42/100\n\n"
        "## Top 3 Strengths\n1. Python background.\n\n"
        "## Critical Issues\n1. No quantified impact.\n\n"
        "## Line-Item Improvements\n"
        "Original: Worked on machine learning projects.\n"
        "Improved: Delivered 3 production ML pipelines reducing inference latency by 40%.\n\n"
        "Before: ML experience\nAfter: Built RAG system serving 10k daily queries"
    )
    with patch("app.agents.resume_reviewer.settings") as mock_settings:
        mock_settings.anthropic_api_key = "fake-key"
        with patch.object(agent, "_build_llm", return_value=_mock_llm(review)):
            result = await agent.execute(state)

    assert result.response == review


@pytest.mark.asyncio
async def test_resume_reviewer_evaluate_good_response() -> None:
    from app.agents.resume_reviewer import ResumeReviewerAgent

    agent = ResumeReviewerAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        response=(
            "## Overall Score: 72/100\n\n"
            "## Line-Item Improvements\n"
            "Before: Worked on AI\nAfter: Deployed RAG pipeline handling 50k requests/day"
        ),
    )
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_resume_reviewer_evaluate_no_score() -> None:
    from app.agents.resume_reviewer import ResumeReviewerAgent

    agent = ResumeReviewerAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        response="Your resume looks good overall. Some improvements needed.",
    )
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == pytest.approx(0.3)


# ── billing_support ────────────────────────────────────────────────────────────
# D10 Checkpoint 4 cutover (commit reference TBD): the legacy
# BillingSupportAgent (BaseAgent subclass) was deleted. The agent
# now lives as an AgenticBaseAgent subclass at the same module path
# (app.agents.billing_support) but registers via _agentic_registry,
# not AGENT_REGISTRY. Its full coverage lives in
# tests/test_agents/test_billing_support.py (3 phantom-escalation
# pin tests + 6 Wave 2 tests covering Pass 3b §7.1 failure classes
# + memory R/W + speculative-lookup integration) plus
# tests/test_agents/tools/agent_specific/billing_support/ (35
# per-tool tests across 4 files).
#
# The original ws4 tests below tested legacy-class behaviors:
#   • test_billing_support_registered (AGENT_REGISTRY membership)
#   • test_billing_support_answers_subscription_question (legacy
#     execute() shape with state mutation)
#   • test_billing_support_guardrail_no_dollar_amounts +
#     _triggers_on_dollar_amount (legacy regex-based evaluate())
#   • test_billing_support_fallback_refund (legacy _fallback_response
#     static text)
# All five removed at cutover. Keeping a retirement pin so a
# future revert is loud.


@pytest.mark.asyncio
async def test_billing_support_no_longer_in_legacy_registry() -> None:
    """D10 Checkpoint 4 cutover pin: billing_support migrated off
    the legacy BaseAgent path. AGENT_REGISTRY no longer carries it;
    the agent lives in _agentic_registry, reachable via the
    canonical /api/v1/agentic/{flow}/chat endpoint.
    """
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered

    _ensure_registered()
    assert "billing_support" not in AGENT_REGISTRY, (
        "billing_support is back in AGENT_REGISTRY — D10 cutover "
        "reverted? See app/agents/registry.py:_ensure_registered + "
        "the new class at app/agents/billing_support.py "
        "(AgenticBaseAgent, registered via _agentic_registry)."
    )


@pytest.mark.asyncio
async def test_senior_engineer_merge_no_longer_in_legacy_registry() -> None:
    """D11 Checkpoint 4 cutover pin: senior_engineer migrated off the
    legacy BaseAgent path AND absorbed code_review + coding_assistant
    (Pass 3c E2 merge). All three legacy AGENT_REGISTRY entries are
    gone. senior_engineer lives in _agentic_registry, reachable via
    the canonical /api/v1/agentic/{flow}/chat endpoint.
    """
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered

    _ensure_registered()
    for legacy_name in ("senior_engineer", "code_review", "coding_assistant"):
        assert legacy_name not in AGENT_REGISTRY, (
            f"{legacy_name!r} is back in AGENT_REGISTRY — D11 cutover "
            "reverted? See app/agents/registry.py:_ensure_registered + "
            "the canonical class at app/agents/senior_engineer.py "
            "(AgenticBaseAgent, registered via _agentic_registry)."
        )


# ── RagService ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rag_service_returns_mock_without_api_key() -> None:
    from app.services.rag_service import RagService

    svc = RagService(api_key=None)
    results = await svc.search("What is RAG?", top_k=2)
    assert len(results) == 2
    assert all("content" in r for r in results)
    assert all("score" in r for r in results)
    assert all("source" in r for r in results)
    # All mock results should mention "RAG"
    assert all("RAG" in r["content"] for r in results)


@pytest.mark.asyncio
async def test_rag_service_returns_mock_with_empty_api_key() -> None:
    from app.services.rag_service import RagService

    svc = RagService(api_key="")
    results = await svc.search("LangGraph", top_k=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_rag_service_upsert_noop_without_key() -> None:
    """upsert_lesson should not raise even when Pinecone is not configured."""
    from app.services.rag_service import RagService

    svc = RagService(api_key=None)
    # Should complete without error
    await svc.upsert_lesson("lesson-001", "RAG content here", {"title": "RAG Lesson"})


@pytest.mark.asyncio
async def test_rag_service_pinecone_import_failure_graceful() -> None:
    """If Pinecone package not available, should fall back to mock results."""
    from app.services.rag_service import RagService
    import sys

    svc = RagService(api_key="some-key")
    # Simulate pinecone not installed by making _get_pinecone return None
    with patch.object(svc, "_get_pinecone", return_value=None):
        results = await svc.search("LangGraph conditional edges")

    assert len(results) > 0


# ── Registry completeness (including WS4 agents) ──────────────────────────────

@pytest.mark.asyncio
async def test_all_ws4_agents_registered() -> None:
    from app.agents.registry import AGENT_REGISTRY, _ensure_registered

    _ensure_registered()
    # billing_support removed in D10 cutover — see retirement pin
    # at test_billing_support_no_longer_in_legacy_registry above.
    new_agents = ["career_coach", "resume_reviewer"]
    for name in new_agents:
        assert name in AGENT_REGISTRY, f"WS4 agent '{name}' not in registry"


@pytest.mark.asyncio
async def test_moa_keyword_routing_ws4() -> None:
    from app.agents.moa import _keyword_route

    assert _keyword_route("I want a career plan for AI engineering") == "career_coach"
    assert _keyword_route("review my resume please") == "resume_reviewer"
    # billing_support keyword routing removed in D10 cutover — the
    # keyword would have routed to a non-existent AGENT_REGISTRY
    # entry. Billing questions reach billing_support via the
    # canonical /api/v1/agentic/{flow}/chat endpoint instead.
    assert _keyword_route("billing issue with my subscription") is None
    assert _keyword_route("cancel subscription now") is None
    assert _keyword_route("what skills do i need to become AI engineer") == "career_coach"
