import pytest
from httpx import AsyncClient

COURSE_PAYLOAD = {
    "title": "GenAI Engineering",
    "slug": "genai-engineering",
    "description": "Learn to build production GenAI systems",
    "price_cents": 9900,
    "difficulty": "intermediate",
    "estimated_hours": 20,
}


async def _admin_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@example.com",
            "full_name": "Admin",
            "password": "admin123",
            "role": "admin",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin123"},
    )
    return resp.json()["access_token"]


async def _student_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.com",
            "full_name": "Student",
            "password": "student123",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.com", "password": "student123"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_list_courses_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/courses")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_admin_can_create_course(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == COURSE_PAYLOAD["slug"]
    assert data["title"] == COURSE_PAYLOAD["title"]


@pytest.mark.asyncio
async def test_student_cannot_create_course(client: AsyncClient) -> None:
    token = await _student_token(client)
    resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_slug_rejected(client: AsyncClient) -> None:
    token = await _admin_token(client)
    await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_course_by_id(client: AsyncClient) -> None:
    token = await _admin_token(client)
    create_resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    course_id = create_resp.json()["id"]
    resp = await client.get(f"/api/v1/courses/{course_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == course_id


@pytest.mark.asyncio
async def test_get_course_not_found(client: AsyncClient) -> None:
    import uuid

    resp = await client.get(f"/api/v1/courses/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_update_course(client: AsyncClient) -> None:
    token = await _admin_token(client)
    create_resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    course_id = create_resp.json()["id"]
    resp = await client.put(
        f"/api/v1/courses/{course_id}",
        json={"is_published": True, "title": "Updated Title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_published"] is True
    assert resp.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_admin_can_delete_course(client: AsyncClient) -> None:
    token = await _admin_token(client)
    create_resp = await client.post(
        "/api/v1/courses",
        json=COURSE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    course_id = create_resp.json()["id"]
    del_resp = await client.delete(
        f"/api/v1/courses/{course_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204
    get_resp = await client.get(f"/api/v1/courses/{course_id}")
    assert get_resp.status_code == 404
