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
    data = resp.json()
    assert data["courses"] == []
    assert data["overall_progress"] == 0.0


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

    # Progress endpoint now returns structured data; no enrollment so courses list is empty
    progress_resp = await client.get(
        "/api/v1/students/me/progress",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert progress_resp.status_code == 200
    # No active enrollment exists, so courses list is empty even though progress record was created
    assert progress_resp.json()["courses"] == []


@pytest.mark.asyncio
async def test_structured_progress_with_enrollment(
    client: AsyncClient, db_session: "AsyncSession"
) -> None:
    """
    Creates a user, a course with 10 lessons, enrolls the user, completes 3 lessons.
    Verifies the structured progress response fields.
    """
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.enrollment import Enrollment

    admin_token = await _register_and_login(client, "structadmin@example.com", "admin")
    student_token = await _register_and_login(client, "structstudent@example.com")

    # Create course
    course_resp = await client.post(
        "/api/v1/courses",
        json={
            "title": "Production RAG Engineering",
            "slug": "production-rag-engineering",
            "price_cents": 0,
            "difficulty": "advanced",
            "estimated_hours": 10,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert course_resp.status_code == 201, course_resp.text
    course_id_str = course_resp.json()["id"]
    course_id = uuid.UUID(course_id_str)

    # Create 10 lessons
    lesson_ids: list[str] = []
    for i in range(1, 11):
        lesson_resp = await client.post(
            "/api/v1/lessons",
            json={
                "course_id": course_id_str,
                "title": f"Lesson {i}: Topic {i}",
                "slug": f"lesson-{i}",
                "order": i,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert lesson_resp.status_code == 201, lesson_resp.text
        lesson_ids.append(lesson_resp.json()["id"])

    # Get the student's ID from /me
    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    student_id = uuid.UUID(me_resp.json()["id"])

    # Directly insert an enrollment record via the shared db_session
    # (no enrollment HTTP endpoint exists in this app)
    enrollment = Enrollment(
        student_id=student_id,
        course_id=course_id,
        status="active",
        enrolled_at=datetime.now(UTC),
        progress_pct=0.0,
    )
    db_session.add(enrollment)
    await db_session.flush()

    # Complete first 3 lessons via the API
    for lesson_id in lesson_ids[:3]:
        resp = await client.post(
            f"/api/v1/students/me/lessons/{lesson_id}/complete",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200

    # Fetch structured progress
    progress_resp = await client.get(
        "/api/v1/students/me/progress",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert progress_resp.status_code == 200
    data = progress_resp.json()

    assert len(data["courses"]) == 1
    course_data = data["courses"][0]

    assert course_data["course_id"] == course_id_str
    assert course_data["course_title"] == "Production RAG Engineering"
    assert course_data["total_lessons"] == 10
    assert course_data["completed_lessons"] == 3
    assert course_data["progress_percentage"] == 30.0

    # next lesson should be lesson 4 (index 3)
    assert course_data["next_lesson_id"] == lesson_ids[3]
    assert course_data["next_lesson_title"] == "Lesson 4: Topic 4"

    assert len(course_data["lessons"]) == 10
    for i, lesson in enumerate(course_data["lessons"]):
        expected_status = "completed" if i < 3 else "not_started"
        assert lesson["status"] == expected_status, f"Lesson {i+1} expected {expected_status}"
        assert lesson["order"] == i + 1

    assert data["overall_progress"] == 30.0
