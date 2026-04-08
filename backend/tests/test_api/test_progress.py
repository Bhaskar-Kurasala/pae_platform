import pytest
from httpx import AsyncClient

COURSE_PAYLOAD = {
    "title": "Progress Test Course",
    "slug": "progress-test-course",
    "price_cents": 0,
    "difficulty": "beginner",
    "estimated_hours": 3,
}


async def _register_and_login(client: AsyncClient, email: str, role: str = "student") -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Test",
            "password": "pass1234",
            "role": role,
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_get_progress_empty(client: AsyncClient) -> None:
    token = await _register_and_login(client, "progress@example.com")
    resp = await client.get(
        "/api/v1/students/me/progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_complete_lesson(client: AsyncClient) -> None:
    admin_token = await _register_and_login(client, "progressadmin@example.com", "admin")
    student_token = await _register_and_login(client, "progressstudent@example.com")

    course_resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    course_id = course_resp.json()["id"]
    lesson_resp = await client.post(
        "/api/v1/lessons",
        json={
            "course_id": course_id,
            "title": "L1",
            "slug": "l1",
            "order": 1,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    lesson_id = lesson_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/students/me/lessons/{lesson_id}/complete",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["completed_at"] is not None


@pytest.mark.asyncio
async def test_complete_lesson_idempotent(client: AsyncClient) -> None:
    """Completing a lesson twice should not create duplicates."""
    admin_token = await _register_and_login(client, "idemadmin@example.com", "admin")
    student_token = await _register_and_login(client, "idemstudent@example.com")

    course_resp = await client.post(
        "/api/v1/courses",
        json={**COURSE_PAYLOAD, "slug": "idem-course"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    course_id = course_resp.json()["id"]
    lesson_resp = await client.post(
        "/api/v1/lessons",
        json={"course_id": course_id, "title": "L2", "slug": "l2", "order": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    lesson_id = lesson_resp.json()["id"]

    await client.post(
        f"/api/v1/students/me/lessons/{lesson_id}/complete",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    resp2 = await client.post(
        f"/api/v1/students/me/lessons/{lesson_id}/complete",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp2.status_code == 200

    progress_resp = await client.get(
        "/api/v1/students/me/progress",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert len(progress_resp.json()) == 1
