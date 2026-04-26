"""Route tests for /api/v1/payments/free-enroll."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Free Enroller",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


async def _seed_course(
    db_session: AsyncSession,
    *,
    slug: str,
    price_cents: int,
    is_published: bool = True,
) -> Course:
    course = Course(
        title=f"Course {slug}",
        slug=slug,
        description="Test",
        price_cents=price_cents,
        is_published=is_published,
        difficulty="beginner",
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


@pytest.mark.asyncio
async def test_free_enroll_for_free_course_returns_200(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    course = await _seed_course(db_session, slug="free-101", price_cents=0)
    token = await _register_and_login(client, "free@enroll.dev")

    resp = await client.post(
        "/api/v1/payments/free-enroll",
        headers={"Authorization": f"Bearer {token}"},
        json={"course_id": str(course.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["course_id"] == str(course.id)
    assert body["entitlement_id"]
    assert body["granted_at"]


@pytest.mark.asyncio
async def test_free_enroll_for_paid_course_returns_400(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    course = await _seed_course(
        db_session, slug="paid-202", price_cents=49900
    )
    token = await _register_and_login(client, "paid@enroll.dev")

    resp = await client.post(
        "/api/v1/payments/free-enroll",
        headers={"Authorization": f"Bearer {token}"},
        json={"course_id": str(course.id)},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_free_enroll_replay_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    course = await _seed_course(db_session, slug="free-303", price_cents=0)
    token = await _register_and_login(client, "replay@enroll.dev")

    first = await client.post(
        "/api/v1/payments/free-enroll",
        headers={"Authorization": f"Bearer {token}"},
        json={"course_id": str(course.id)},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["entitlement_id"]

    second = await client.post(
        "/api/v1/payments/free-enroll",
        headers={"Authorization": f"Bearer {token}"},
        json={"course_id": str(course.id)},
    )
    assert second.status_code == 200, second.text
    assert second.json()["entitlement_id"] == first_id
