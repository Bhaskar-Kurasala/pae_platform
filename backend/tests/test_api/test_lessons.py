import uuid

import pytest
from httpx import AsyncClient

COURSE_PAYLOAD = {
    "title": "Lesson Test Course",
    "slug": "lesson-test-course",
    "price_cents": 0,
    "difficulty": "beginner",
    "estimated_hours": 5,
}


async def _admin_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "lessonadmin@example.com",
            "full_name": "Admin",
            "password": "admin123",
            "role": "admin",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "lessonadmin@example.com", "password": "admin123"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_list_lessons_for_course(client: AsyncClient) -> None:
    token = await _admin_token(client)
    course_resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    course_id = course_resp.json()["id"]
    resp = await client.get(f"/api/v1/courses/{course_id}/lessons")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_admin_can_create_lesson(client: AsyncClient) -> None:
    token = await _admin_token(client)
    course_resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    course_id = course_resp.json()["id"]

    lesson_payload = {
        "course_id": course_id,
        "title": "Intro to LangGraph",
        "slug": "intro-langgraph",
        "duration_seconds": 900,
        "order": 1,
    }
    resp = await client.post(
        "/api/v1/lessons",
        json=lesson_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "intro-langgraph"


@pytest.mark.asyncio
async def test_get_lesson_not_found(client: AsyncClient) -> None:
    resp = await client.get(f"/api/v1/lessons/{uuid.uuid4()}")
    assert resp.status_code == 404
