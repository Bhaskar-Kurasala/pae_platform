"""Integration tests for career API routes (#168 #169 #171 #172 #173).

Claude-powered endpoints (resume summary, learning plan) mock the Anthropic
client to avoid live API calls in tests.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTER_PAYLOAD = {
    "email": "careertest@example.com",
    "full_name": "Career Tester",
    "password": "testpass123",
}


async def _get_token(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["email"],
            "password": REGISTER_PAYLOAD["password"],
        },
    )
    return str(resp.json()["access_token"])


def _mock_anthropic_response(text: str) -> Any:
    """Return a mock AsyncAnthropic.messages.create response."""
    content_block = MagicMock()
    content_block.text = text
    mock_response = MagicMock()
    mock_response.content = [content_block]
    return mock_response


# ---------------------------------------------------------------------------
# Resume tests (#168)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_resume_creates_row(client: AsyncClient) -> None:
    """GET /career/resume creates a resume row on first call (no summary yet)."""
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    mock_resp = _mock_anthropic_response("Experienced AI engineer.")
    with patch(
        "app.services.career_service.AsyncAnthropic"
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        mock_instance.messages.create = AsyncMock(return_value=mock_resp)

        resp = await client.get("/api/v1/career/resume", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "title" in data


@pytest.mark.asyncio
async def test_get_resume_returns_existing(client: AsyncClient) -> None:
    """GET /career/resume returns cached summary on second call."""
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    mock_resp = _mock_anthropic_response("Experienced AI engineer.")
    with patch("app.services.career_service.AsyncAnthropic") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        mock_instance.messages.create = AsyncMock(return_value=mock_resp)

        # First call — generates summary
        r1 = await client.get("/api/v1/career/resume", headers=headers)
        assert r1.status_code == 200

        # Second call — should return same data (create not called again)
        r2 = await client.get("/api/v1/career/resume", headers=headers)
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]


# ---------------------------------------------------------------------------
# Fit score tests (#171)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fit_score_returns_valid_structure(client: AsyncClient) -> None:
    token = await _get_token(client)
    resp = await client.post(
        "/api/v1/career/fit-score",
        json={
            "jd_text": "Python FastAPI LLM experience required",
            "jd_title": "AI Engineer",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "fit_score" in data
    assert "matched_skills" in data
    assert "skill_gap" in data
    assert 0.0 <= data["fit_score"] <= 1.0


@pytest.mark.asyncio
async def test_fit_score_no_jd_skills_gives_zero(client: AsyncClient) -> None:
    token = await _get_token(client)
    resp = await client.post(
        "/api/v1/career/fit-score",
        json={
            "jd_text": "Someone awesome.",
            "jd_title": "Generalist",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["fit_score"] == 0.0


# ---------------------------------------------------------------------------
# Learning plan tests (#173)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learning_plan_returns_plan(client: AsyncClient) -> None:
    token = await _get_token(client)
    mock_resp = _mock_anthropic_response(
        "Week 1: Learn Docker basics. Week 2: Kubernetes. Week 3: CI/CD. Week 4: Deploy."
    )
    with patch("app.services.career_service.AsyncAnthropic") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        mock_instance.messages.create = AsyncMock(return_value=mock_resp)

        resp = await client.post(
            "/api/v1/career/learning-plan",
            json={
                "jd_text": "Kubernetes Docker required",
                "jd_title": "DevOps Engineer",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "plan" in data
    assert "skill_gap" in data
    assert isinstance(data["skill_gap"], list)


@pytest.mark.asyncio
async def test_learning_plan_no_gap_returns_prep_message(client: AsyncClient) -> None:
    """When JD has no extractable skills, returns no-gap message without API call."""
    token = await _get_token(client)
    resp = await client.post(
        "/api/v1/career/learning-plan",
        json={"jd_text": "Someone awesome.", "jd_title": "Generalist"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "interview" in resp.json()["plan"].lower()


# ---------------------------------------------------------------------------
# Interview question bank tests (#169)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interview_questions_returns_list(client: AsyncClient) -> None:
    token = await _get_token(client)
    resp = await client.get(
        "/api/v1/career/interview-questions?q=python",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_interview_questions_empty_query(client: AsyncClient) -> None:
    token = await _get_token(client)
    resp = await client.get(
        "/api/v1/career/interview-questions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_career_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/career/resume")
    assert resp.status_code == 401
