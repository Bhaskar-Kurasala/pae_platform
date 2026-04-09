from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

REGISTER_PAYLOAD = {
    "email": "agent_test@example.com",
    "full_name": "Agent Tester",
    "password": "pass1234",
}


async def _get_token(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_chat_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/agents/chat",
        json={"message": "What is RAG?"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_endpoint_with_mock(client: AsyncClient) -> None:
    """Chat endpoint should route and return a response (LLM mocked)."""
    token = await _get_token(client)

    mock_result = {
        "response": "What do you think RAG solves? Have you considered knowledge cutoff?",
        "agent_name": "socratic_tutor",
        "evaluation_score": 0.9,
        "conversation_id": "test-conv-id",
    }

    with patch(
        "app.services.agent_orchestrator.AgentOrchestratorService.chat",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = await client.post(
            "/api/v1/agents/chat",
            json={"message": "What is RAG?", "agent_name": "socratic_tutor"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_name"] == "socratic_tutor"
    assert "?" in data["response"]
    assert data["evaluation_score"] == 0.9
    assert "conversation_id" in data


@pytest.mark.asyncio
async def test_chat_returns_conversation_id(client: AsyncClient) -> None:
    token = await _get_token(client)

    mock_result = {
        "response": "Let me ask you something first — what do you already know about this topic?",
        "agent_name": "socratic_tutor",
        "evaluation_score": 0.9,
        "conversation_id": "abc-123",
    }

    with patch(
        "app.services.agent_orchestrator.AgentOrchestratorService.chat",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = await client.post(
            "/api/v1/agents/chat",
            json={"message": "help"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.json()["conversation_id"] == "abc-123"


@pytest.mark.asyncio
async def test_list_agents_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/agents/list")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient) -> None:
    token = await _get_token(client)
    resp = await client.get(
        "/api/v1/agents/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    agents = resp.json()
    names = [a["name"] for a in agents]
    assert "socratic_tutor" in names
    assert "code_review" in names
    assert "adaptive_quiz" in names
