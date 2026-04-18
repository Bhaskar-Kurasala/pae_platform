import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.skill_seed_service import seed_skill_graph


async def _register_and_login(
    client: AsyncClient, email: str = "skillpath@example.com"
) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Path Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_path_without_goal_uses_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    token = await _register_and_login(client)
    resp = await client.get(
        "/api/v1/skills/path",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["motivation"] is None
    # default includes claude-api + ancestors
    assert "claude-api" in body["slugs"]
    assert "llm-fundamentals" in body["slugs"]


@pytest.mark.asyncio
async def test_path_respects_interview_motivation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    token = await _register_and_login(client, "interview_path@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    goal = await client.post(
        "/api/v1/goals/me",
        json={
            "motivation": "interview",
            "deadline_months": 3,
            "success_statement": "Pass my FAANG AI eng loop.",
        },
        headers=headers,
    )
    assert goal.status_code in (200, 201)

    resp = await client.get("/api/v1/skills/path", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["motivation"] == "interview"
    assert "fastapi" in body["slugs"]
    assert "llm-fundamentals" in body["slugs"]
    # off-path (for interview) shouldn't be flagged
    assert "multi-agent" not in body["slugs"]


@pytest.mark.asyncio
async def test_path_ancestors_included(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Confirms prereq closure: if agent-design is a target, function-calling
    and claude-api and llm-fundamentals must be in the path."""
    await seed_skill_graph(db_session)
    token = await _register_and_login(client, "ancestors@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(
        "/api/v1/goals/me",
        json={
            "motivation": "skill_up",
            "deadline_months": 6,
            "success_statement": "Ship a production RAG at work.",
        },
        headers=headers,
    )
    body = (await client.get("/api/v1/skills/path", headers=headers)).json()
    assert "agent-design" in body["slugs"]
    assert "function-calling" in body["slugs"]
    assert "claude-api" in body["slugs"]
    assert "llm-fundamentals" in body["slugs"]


@pytest.mark.asyncio
async def test_path_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/skills/path")
    assert resp.status_code in (401, 403)
