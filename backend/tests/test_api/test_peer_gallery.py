"""Tests for the peer-solutions gallery (P2-07)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.exercise import Exercise
from app.models.lesson import Lesson


async def _register_and_login(
    client: AsyncClient, email: str, role: str = "student"
) -> tuple[str, str]:
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "T", "password": "pass1234", "role": role},
    )
    user_id = reg.json()["id"]
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return resp.json()["access_token"], user_id


async def _seed_exercise(db: AsyncSession) -> uuid.UUID:
    course = Course(
        title="Peer Course",
        slug=f"peer-course-{uuid.uuid4().hex[:8]}",
        description="",
        price_cents=0,
        difficulty="beginner",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    lesson = Lesson(
        course_id=course.id,
        title="Peer Lesson",
        slug=f"peer-lesson-{uuid.uuid4().hex[:8]}",
        order=1,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)

    exercise = Exercise(
        lesson_id=lesson.id,
        title="Peer Exercise",
        description="Write a greet() function.",
        order=1,
    )
    db.add(exercise)
    await db.commit()
    await db.refresh(exercise)
    return exercise.id


@pytest.mark.asyncio
async def test_gallery_hides_private_submissions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    exercise_id = await _seed_exercise(db_session)
    author_token, _ = await _register_and_login(client, "private@test.dev")
    viewer_token, _ = await _register_and_login(client, "viewer1@test.dev")

    # Author submits without opting in to sharing.
    await client.post(
        f"/api/v1/exercises/{exercise_id}/submit",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"code": "def greet(n): return 'hi ' + n", "shared_with_peers": False},
    )

    resp = await client.get(
        f"/api/v1/exercises/{exercise_id}/peer-gallery",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_gallery_returns_shared_submissions_anonymized(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    exercise_id = await _seed_exercise(db_session)
    author_token, author_id = await _register_and_login(client, "author@test.dev")
    viewer_token, _ = await _register_and_login(client, "viewer2@test.dev")

    await client.post(
        f"/api/v1/exercises/{exercise_id}/submit",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "code": "def greet(n): return f'hi {n}'",
            "shared_with_peers": True,
            "share_note": "Used f-strings for readability.",
        },
    )

    resp = await client.get(
        f"/api/v1/exercises/{exercise_id}/peer-gallery",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert "f'hi {n}'" in item["code"]
    assert item["share_note"] == "Used f-strings for readability."
    # Anonymized — no email, no full name.
    assert item["author_handle"].startswith("peer_")
    assert "author@test.dev" not in str(item)
    # Handle is deterministic from the author's user id.
    assert author_id.replace("-", "")[:6] in item["author_handle"]


@pytest.mark.asyncio
async def test_gallery_excludes_viewers_own_submission(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    exercise_id = await _seed_exercise(db_session)
    me_token, _ = await _register_and_login(client, "me@test.dev")

    await client.post(
        f"/api/v1/exercises/{exercise_id}/submit",
        headers={"Authorization": f"Bearer {me_token}"},
        json={"code": "mine", "shared_with_peers": True},
    )

    resp = await client.get(
        f"/api/v1/exercises/{exercise_id}/peer-gallery",
        headers={"Authorization": f"Bearer {me_token}"},
    )
    # Gallery hides my own work — I'm here to see others, not myself.
    assert resp.json() == []


@pytest.mark.asyncio
async def test_share_patch_flips_visibility(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    exercise_id = await _seed_exercise(db_session)
    author_token, _ = await _register_and_login(client, "flipper@test.dev")
    viewer_token, _ = await _register_and_login(client, "viewer3@test.dev")

    sub = await client.post(
        f"/api/v1/exercises/{exercise_id}/submit",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"code": "x = 1", "shared_with_peers": False},
    )
    sub_id = sub.json()["id"]

    # Not shared yet.
    g1 = await client.get(
        f"/api/v1/exercises/{exercise_id}/peer-gallery",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert g1.json() == []

    # Flip to shared.
    await client.patch(
        f"/api/v1/exercises/submissions/{sub_id}/share",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"shared_with_peers": True, "share_note": "sharing now"},
    )

    g2 = await client.get(
        f"/api/v1/exercises/{exercise_id}/peer-gallery",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert len(g2.json()) == 1
    assert g2.json()[0]["share_note"] == "sharing now"


@pytest.mark.asyncio
async def test_cannot_share_someone_elses_submission(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    exercise_id = await _seed_exercise(db_session)
    author_token, _ = await _register_and_login(client, "real-author@test.dev")
    attacker_token, _ = await _register_and_login(client, "attacker@test.dev")

    sub = await client.post(
        f"/api/v1/exercises/{exercise_id}/submit",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"code": "secret", "shared_with_peers": False},
    )
    sub_id = sub.json()["id"]

    # Attacker tries to flip someone else's submission to public.
    resp = await client.patch(
        f"/api/v1/exercises/submissions/{sub_id}/share",
        headers={"Authorization": f"Bearer {attacker_token}"},
        json={"shared_with_peers": True},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_gallery_requires_auth(client: AsyncClient) -> None:
    resp = await client.get(f"/api/v1/exercises/{uuid.uuid4()}/peer-gallery")
    assert resp.status_code == 401
