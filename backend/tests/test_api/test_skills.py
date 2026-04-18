import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.skill_seed_service import seed_skill_graph


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Skill Tester",
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
async def test_get_graph_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/skills/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"nodes": [], "edges": []}


@pytest.mark.asyncio
async def test_get_graph_returns_seeded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    resp = await client.get("/api/v1/skills/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) == 40
    assert len(body["edges"]) == 41
    node = body["nodes"][0]
    assert set(node) >= {"id", "slug", "name", "description", "difficulty"}


@pytest.mark.asyncio
async def test_get_my_states_empty_for_new_user(client: AsyncClient) -> None:
    token = await _register_and_login(client, "skills_me_empty@example.com")
    resp = await client.get(
        "/api/v1/skills/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_touch_creates_state_and_updates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    graph = (await client.get("/api/v1/skills/graph")).json()
    skill_id = graph["nodes"][0]["id"]

    token = await _register_and_login(client, "skills_touch@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = await client.post(f"/api/v1/skills/{skill_id}/touch", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["skill_id"] == skill_id
    first_ts = r1.json()["last_touched_at"]

    states = (await client.get("/api/v1/skills/me", headers=headers)).json()
    assert len(states) == 1
    assert states[0]["skill_id"] == skill_id
    assert states[0]["mastery_level"] == "novice"

    r2 = await client.post(f"/api/v1/skills/{skill_id}/touch", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["last_touched_at"] >= first_ts

    states_after = (await client.get("/api/v1/skills/me", headers=headers)).json()
    assert len(states_after) == 1


@pytest.mark.asyncio
async def test_touch_unknown_skill_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "skills_404@example.com")
    resp = await client.post(
        "/api/v1/skills/00000000-0000-0000-0000-000000000000/touch",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_touch_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/skills/00000000-0000-0000-0000-000000000000/touch"
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/skills/me")
    assert resp.status_code in (401, 403)
