import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.skill_seed_service import seed_skill_graph


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Diagnostic Tester",
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
async def test_get_questions_returns_10(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/diagnostic/questions")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["questions"]) == 10
    assert len(body["scale"]) == 5
    for q in body["questions"]:
        assert set(q) == {"id", "skill_slug", "prompt"}


@pytest.mark.asyncio
async def test_submit_writes_user_skill_states(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    token = await _register_and_login(client, "diag_submit@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "answers": [
            {"skill_slug": "python-basics", "rating": 5},
            {"skill_slug": "fastapi", "rating": 3},
            {"skill_slug": "rag-basics", "rating": 1},
        ]
    }
    resp = await client.post(
        "/api/v1/diagnostic/submit", json=payload, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"states_updated": 3}

    states = (await client.get("/api/v1/skills/me", headers=headers)).json()
    by_skill = {}
    skills = (await client.get("/api/v1/skills/graph")).json()["nodes"]
    slug_by_id = {s["id"]: s["slug"] for s in skills}
    for s in states:
        by_skill[slug_by_id[s["skill_id"]]] = s

    assert by_skill["python-basics"]["mastery_level"] == "mastered"
    assert by_skill["python-basics"]["confidence"] == 0.9
    assert by_skill["fastapi"]["mastery_level"] == "learning"
    assert by_skill["rag-basics"]["mastery_level"] == "unknown"


@pytest.mark.asyncio
async def test_submit_updates_existing_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    token = await _register_and_login(client, "diag_update@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(
        "/api/v1/diagnostic/submit",
        json={"answers": [{"skill_slug": "python-basics", "rating": 2}]},
        headers=headers,
    )
    resp = await client.post(
        "/api/v1/diagnostic/submit",
        json={"answers": [{"skill_slug": "python-basics", "rating": 4}]},
        headers=headers,
    )
    assert resp.status_code == 200

    states = (await client.get("/api/v1/skills/me", headers=headers)).json()
    assert len(states) == 1
    assert states[0]["mastery_level"] == "proficient"
    assert states[0]["confidence"] == 0.7


@pytest.mark.asyncio
async def test_submit_ignores_unknown_slugs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    token = await _register_and_login(client, "diag_unknown@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/diagnostic/submit",
        json={
            "answers": [
                {"skill_slug": "python-basics", "rating": 3},
                {"skill_slug": "does-not-exist", "rating": 5},
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 200
    # unknown slug silently dropped; counter only counts resolved skills
    assert resp.json() == {"states_updated": 1}


@pytest.mark.asyncio
async def test_submit_rejects_bad_rating(client: AsyncClient) -> None:
    token = await _register_and_login(client, "diag_bad@example.com")
    resp = await client.post(
        "/api/v1/diagnostic/submit",
        json={"answers": [{"skill_slug": "python-basics", "rating": 99}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_submit_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/diagnostic/submit", json={"answers": []}
    )
    assert resp.status_code in (401, 403)
