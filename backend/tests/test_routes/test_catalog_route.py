"""Route tests for /api/v1/catalog."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.course_bundle import CourseBundle


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Catalog User",
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
    difficulty: str = "intermediate",
) -> Course:
    course = Course(
        title=f"Course {slug}",
        slug=slug,
        description=f"About {slug}",
        price_cents=price_cents,
        is_published=is_published,
        difficulty=difficulty,
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


async def _seed_bundle(
    db_session: AsyncSession,
    *,
    slug: str,
    course_ids: list[uuid.UUID],
    is_published: bool = True,
) -> CourseBundle:
    bundle = CourseBundle(
        slug=slug,
        title=f"Bundle {slug}",
        description=f"Bundle of {len(course_ids)} courses",
        price_cents=99900,
        currency="INR",
        course_ids=[str(cid) for cid in course_ids],
        metadata_={},
        is_published=is_published,
        sort_order=0,
    )
    db_session.add(bundle)
    await db_session.commit()
    await db_session.refresh(bundle)
    return bundle


@pytest.mark.asyncio
async def test_catalog_anon_returns_published_courses_locked(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _seed_course(db_session, slug="cat-pub", price_cents=49900)
    await _seed_course(
        db_session,
        slug="cat-unpub",
        price_cents=49900,
        is_published=False,
    )

    resp = await client.get("/api/v1/catalog/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    slugs = {c["slug"] for c in body["courses"]}
    assert "cat-pub" in slugs
    assert "cat-unpub" not in slugs
    for course in body["courses"]:
        assert course["is_unlocked"] is False


@pytest.mark.asyncio
async def test_catalog_auth_user_with_entitlement_sees_unlocked(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _seed_course(db_session, slug="cat-free", price_cents=0)
    paid_course = await _seed_course(
        db_session, slug="cat-paid", price_cents=49900
    )

    token = await _register_and_login(client, "ent@catalog.dev")

    # Auto-grant via free-enroll for the paid course is not possible — instead
    # call entitlement_service directly to seed a purchase entitlement.
    from app.services import entitlement_service

    # We need the user's id; resolve via the /me endpoint for realism.
    me_resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    user_id = uuid.UUID(me_resp.json()["id"])

    await entitlement_service.grant_entitlement(
        db_session,
        user_id=user_id,
        course_id=paid_course.id,
        source="purchase",
        source_ref=None,
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/catalog/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_slug = {c["slug"]: c for c in body["courses"]}
    # Free course is implicitly unlocked because is_entitled short-circuits.
    assert by_slug["cat-free"]["is_unlocked"] is True
    # Paid course unlocked because of the explicit purchase entitlement.
    assert by_slug["cat-paid"]["is_unlocked"] is True


@pytest.mark.asyncio
async def test_catalog_includes_published_bundles(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    course_a = await _seed_course(
        db_session, slug="cat-bundle-a", price_cents=49900
    )
    course_b = await _seed_course(
        db_session, slug="cat-bundle-b", price_cents=49900
    )
    await _seed_bundle(
        db_session,
        slug="bundle-pub",
        course_ids=[course_a.id, course_b.id],
        is_published=True,
    )
    await _seed_bundle(
        db_session,
        slug="bundle-unpub",
        course_ids=[course_a.id],
        is_published=False,
    )

    resp = await client.get("/api/v1/catalog/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    bundle_slugs = {b["slug"] for b in body["bundles"]}
    assert "bundle-pub" in bundle_slugs
    assert "bundle-unpub" not in bundle_slugs
    pub = next(b for b in body["bundles"] if b["slug"] == "bundle-pub")
    assert len(pub["course_ids"]) == 2
    assert pub["price_cents"] == 99900
