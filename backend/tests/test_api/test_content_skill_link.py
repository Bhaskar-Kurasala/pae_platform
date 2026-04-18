import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.skill_seed_service import seed_skill_graph


async def _register_admin(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin_skill@example.com",
            "full_name": "Admin",
            "password": "pass1234",
            "role": "admin",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_skill@example.com", "password": "pass1234"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_create_lesson_with_skill_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    token = await _register_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    course = await client.post(
        "/api/v1/courses",
        json={"title": "c", "slug": "c", "price_cents": 0, "difficulty": "beginner"},
        headers=headers,
    )
    assert course.status_code == 201
    course_id = course.json()["id"]

    skills = (await client.get("/api/v1/skills/graph")).json()["nodes"]
    skill_id = next(s["id"] for s in skills if s["slug"] == "fastapi")

    resp = await client.post(
        "/api/v1/lessons",
        json={
            "course_id": course_id,
            "title": "L1",
            "slug": "l1",
            "skill_id": skill_id,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["skill_id"] == skill_id


@pytest.mark.asyncio
async def test_update_lesson_skill_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_skill_graph(db_session)
    token = await _register_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    course = (
        await client.post(
            "/api/v1/courses",
            json={
                "title": "c",
                "slug": "c2",
                "price_cents": 0,
                "difficulty": "beginner",
            },
            headers=headers,
        )
    ).json()
    lesson = (
        await client.post(
            "/api/v1/lessons",
            json={"course_id": course["id"], "title": "L", "slug": "l2"},
            headers=headers,
        )
    ).json()
    assert lesson["skill_id"] is None

    skills = (await client.get("/api/v1/skills/graph")).json()["nodes"]
    skill_id = next(s["id"] for s in skills if s["slug"] == "rag-basics")

    upd = await client.put(
        f"/api/v1/lessons/{lesson['id']}",
        json={"skill_id": skill_id},
        headers=headers,
    )
    assert upd.status_code == 200
    assert upd.json()["skill_id"] == skill_id
