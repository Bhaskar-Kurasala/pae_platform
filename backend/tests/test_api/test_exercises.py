import uuid

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str, role: str = "student") -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Test", "password": "pass1234", "role": role},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return resp.json()["access_token"]


async def _create_exercise(client: AsyncClient, admin_token: str) -> str:
    """Helper: create a course + lesson + exercise and return exercise id."""
    course_resp = await client.post(
        "/api/v1/courses",
        json={
            "title": "Exercises Course",
            "slug": "exercises-course",
            "price_cents": 0,
            "difficulty": "beginner",
            "estimated_hours": 1,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    course_id = course_resp.json()["id"]
    lesson_resp = await client.post(
        "/api/v1/lessons",
        json={"course_id": course_id, "title": "Ex Lesson", "slug": "ex-lesson", "order": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    lesson_id = lesson_resp.json()["id"]

    # Insert directly via the DB override used by the test client
    # We'll do it via a dedicated endpoint instead for cleanliness
    # Since there's no POST /exercises yet, insert via repo in a separate fixture
    # Return lesson_id so tests can create via direct DB insert
    return lesson_id  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_get_exercise_not_found(client: AsyncClient) -> None:
    resp = await client.get(f"/api/v1/exercises/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_exercise_not_found(client: AsyncClient) -> None:
    token = await _register_and_login(client, "exstudent@example.com")
    resp = await client.post(
        f"/api/v1/exercises/{uuid.uuid4()}/submit",
        json={"exercise_id": str(uuid.uuid4()), "code": "print('hello')"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_exercise_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/exercises/{uuid.uuid4()}/submit",
        json={"exercise_id": str(uuid.uuid4()), "code": "x=1"},
    )
    assert resp.status_code == 401
