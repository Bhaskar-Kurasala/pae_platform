import uuid

import pytest
from httpx import AsyncClient

COURSE_PAYLOAD = {
    "title": "GenAI Engineering",
    "slug": "genai-enroll-test",
    "description": "Learn to build production GenAI systems",
    "price_cents": 9900,
    "difficulty": "intermediate",
    "estimated_hours": 20,
}


async def _register_and_login(client: AsyncClient, email: str, password: str, role: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Test User", "password": password, "role": role},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()["access_token"]


async def _create_published_course(client: AsyncClient, admin_token: str) -> str:
    """Create a course then publish it, returning its id."""
    create_resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    course_id = create_resp.json()["id"]
    await client.put(
        f"/api/v1/courses/{course_id}",
        json={"is_published": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    return course_id


@pytest.mark.asyncio
async def test_enroll_in_published_course_returns_201(client: AsyncClient) -> None:
    admin_token = await _register_and_login(client, "admin_enroll@example.com", "pass1234", "admin")
    student_token = await _register_and_login(
        client, "student_enroll@example.com", "pass1234", "student"
    )
    course_id = await _create_published_course(client, admin_token)

    resp = await client.post(
        f"/api/v1/courses/{course_id}/enroll",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["course_id"] == course_id
    assert data["status"] == "active"
    assert data["progress_pct"] == 0.0
    assert "id" in data
    assert "student_id" in data
    assert "enrolled_at" in data


@pytest.mark.asyncio
async def test_enroll_twice_returns_409(client: AsyncClient) -> None:
    admin_token = await _register_and_login(
        client, "admin_dup@example.com", "pass1234", "admin"
    )
    student_token = await _register_and_login(
        client, "student_dup@example.com", "pass1234", "student"
    )
    course_id = await _create_published_course(client, admin_token)

    await client.post(
        f"/api/v1/courses/{course_id}/enroll",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    resp = await client.post(
        f"/api/v1/courses/{course_id}/enroll",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 409
    assert "Already enrolled" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_enroll_nonexistent_course_returns_404(client: AsyncClient) -> None:
    student_token = await _register_and_login(
        client, "student_404@example.com", "pass1234", "student"
    )
    resp = await client.post(
        f"/api/v1/courses/{uuid.uuid4()}/enroll",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_enroll_without_auth_returns_401(client: AsyncClient) -> None:
    resp = await client.post(f"/api/v1/courses/{uuid.uuid4()}/enroll")
    assert resp.status_code == 401
