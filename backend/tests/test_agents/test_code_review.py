import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base_agent import AgentState
from app.agents.code_review import CodeReviewAgent, analyze_code

SAMPLE_CODE = '''
import os

async def get_data(user_id: str):
    api_key = "hardcoded-secret-key-123"
    result = requests.get(f"https://api.example.com/data/{user_id}")
    return result.json()
'''

SAMPLE_REVIEW = {
    "score": 35,
    "summary": "The code has critical security issues and lacks production-readiness.",
    "strengths": ["Type hint on user_id"],
    "issues": [
        {
            "severity": "critical",
            "line": "api_key = ...",
            "issue": "Hardcoded API key",
            "suggestion": "Use pydantic-settings / environment variables",
        }
    ],
    "dimension_scores": {
        "correctness": 10,
        "production_readiness": 5,
        "llm_best_practices": 10,
        "code_quality": 5,
        "performance": 5,
    },
    "approved": False,
}


def _make_mock_llm(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
    return mock_llm


@pytest.mark.asyncio
async def test_code_review_registered() -> None:
    import app.agents.code_review  # noqa: F401
    from app.agents.registry import AGENT_REGISTRY

    assert "code_review" in AGENT_REGISTRY


@pytest.mark.asyncio
async def test_analyze_code_detects_secrets() -> None:
    """Static analysis tool should flag hardcoded credentials."""
    result = analyze_code.invoke({"code": 'api_key = "sk-secret-123"'})
    assert "credential" in result.lower() or "WARNING" in result


@pytest.mark.asyncio
async def test_analyze_code_clean() -> None:
    clean_code = 'from app.core.config import settings\n\ndef foo() -> None:\n    pass\n'
    result = analyze_code.invoke({"code": clean_code})
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_code_review_execute_returns_json() -> None:
    agent = CodeReviewAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={"code": SAMPLE_CODE},
    )

    with patch.object(agent, "_build_llm", return_value=_make_mock_llm(json.dumps(SAMPLE_REVIEW))):
        result = await agent.execute(state)

    parsed = json.loads(result.response or "{}")
    assert parsed["score"] == 35
    assert parsed["approved"] is False
    assert "analyze_code" in result.tools_used


@pytest.mark.asyncio
async def test_code_review_evaluation_score() -> None:
    agent = CodeReviewAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        response=json.dumps({"score": 80, "approved": True}),
    )
    evaluated = await agent.evaluate(state)
    assert evaluated.evaluation_score == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_code_review_handles_malformed_llm_output() -> None:
    """If LLM returns non-JSON, should not crash — fallback gracefully."""
    agent = CodeReviewAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={"code": "x = 1"},
    )

    with patch.object(agent, "_build_llm", return_value=_make_mock_llm("Sorry, I can't review that.")):
        result = await agent.execute(state)

    # Should have response (even if raw text)
    assert result.response is not None


@pytest.mark.asyncio
async def test_code_review_parses_markdown_json() -> None:
    """LLM sometimes wraps JSON in markdown fences."""
    agent = CodeReviewAgent()
    state = AgentState(
        student_id="s1",
        task="review",
        context={"code": "print('hello')"},
    )

    fenced = f"```json\n{json.dumps(SAMPLE_REVIEW)}\n```"
    with patch.object(agent, "_build_llm", return_value=_make_mock_llm(fenced)):
        result = await agent.execute(state)

    parsed = json.loads(result.response or "{}")
    assert parsed["score"] == 35
