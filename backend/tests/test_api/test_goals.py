import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Goal Tester",
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
async def test_get_goal_returns_404_when_missing(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_missing@example.com")
    resp = await client.get(
        "/api/v1/goals/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_goal_contract(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_create@example.com")
    payload = {
        "motivation": "career_switch",
        "deadline_months": 6,
        "success_statement": "Ship a production RAG system end-to-end.",
    }
    resp = await client.post(
        "/api/v1/goals/me",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["motivation"] == "career_switch"
    assert data["deadline_months"] == 6
    assert data["success_statement"] == "Ship a production RAG system end-to-end."
    assert "id" in data
    assert "user_id" in data


@pytest.mark.asyncio
async def test_post_goal_is_upsert(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_upsert@example.com")
    first = {
        "motivation": "skill_up",
        "deadline_months": 3,
        "success_statement": "Understand agent orchestration deeply.",
    }
    resp1 = await client.post(
        "/api/v1/goals/me",
        json=first,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 201
    goal_id_1 = resp1.json()["id"]

    second = {
        "motivation": "interview",
        "deadline_months": 2,
        "success_statement": "Ace a senior AI engineering interview loop.",
    }
    resp2 = await client.post(
        "/api/v1/goals/me",
        json=second,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200  # updated, not created
    data = resp2.json()
    assert data["id"] == goal_id_1  # same row
    assert data["motivation"] == "interview"
    assert data["deadline_months"] == 2


@pytest.mark.asyncio
async def test_get_goal_after_create(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_get@example.com")
    await client.post(
        "/api/v1/goals/me",
        json={
            "motivation": "curiosity",
            "deadline_months": 12,
            "success_statement": "Build a personal knowledge assistant.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get(
        "/api/v1/goals/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["motivation"] == "curiosity"
    assert data["deadline_months"] == 12


@pytest.mark.asyncio
async def test_patch_goal_partial_update(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_patch@example.com")
    await client.post(
        "/api/v1/goals/me",
        json={
            "motivation": "career_switch",
            "deadline_months": 9,
            "success_statement": "Land an AI engineer role at a top startup.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.patch(
        "/api/v1/goals/me",
        json={"deadline_months": 4},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["deadline_months"] == 4
    assert data["motivation"] == "career_switch"  # unchanged
    assert data["success_statement"].startswith("Land")  # unchanged


@pytest.mark.asyncio
async def test_patch_goal_returns_404_when_missing(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_patch_missing@example.com")
    resp = await client.patch(
        "/api/v1/goals/me",
        json={"deadline_months": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_goal_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/goals/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_motivation_enum_validation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_enum@example.com")
    resp = await client.post(
        "/api/v1/goals/me",
        json={
            "motivation": "invalid_value",
            "deadline_months": 3,
            "success_statement": "A statement long enough to pass min_length.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_deadline_range_validation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "goal_range@example.com")
    resp = await client.post(
        "/api/v1/goals/me",
        json={
            "motivation": "skill_up",
            "deadline_months": 0,
            "success_statement": "A statement long enough to pass min_length.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_goals_are_per_user(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "goal_user_a@example.com")
    token_b = await _register_and_login(client, "goal_user_b@example.com")

    await client.post(
        "/api/v1/goals/me",
        json={
            "motivation": "career_switch",
            "deadline_months": 6,
            "success_statement": "User A goal statement here.",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = await client.get(
        "/api/v1/goals/me",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 404  # B has no goal yet
