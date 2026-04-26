"""Tests for app.api.v1.dependencies.entitlement.require_course_access.

We mount the dependency on a tiny throwaway FastAPI app so the test
exercises the real dependency wiring (path-param plumbing, get_db,
get_current_user) without coupling to any production route file.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.dependencies.entitlement import require_course_access
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.course import Course
from app.models.course_entitlement import (
    ENTITLEMENT_SOURCE_PURCHASE,
    CourseEntitlement,
)
from app.models.user import User


def _build_app(db_session, user: User) -> FastAPI:
    """Tiny FastAPI app that mounts the dependency once."""
    app = FastAPI()

    @app.get(
        "/courses/{course_id}/probe",
        dependencies=[Depends(require_course_access())],
    )
    async def probe(course_id: uuid.UUID) -> dict:
        return {"ok": True, "course_id": str(course_id)}

    async def _override_db():
        yield db_session

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


async def _make_user(db_session) -> User:
    user = User(
        email=f"dep-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Dep Tester",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_course(
    db_session,
    *,
    slug: str,
    price_cents: int = 9900,
    is_published: bool = True,
) -> Course:
    course = Course(
        title=f"Course {slug}",
        slug=slug,
        description="x",
        price_cents=price_cents,
        is_published=is_published,
        difficulty="beginner",
        estimated_hours=1,
    )
    db_session.add(course)
    await db_session.flush()
    return course


@pytest.mark.asyncio
async def test_require_course_access_200_when_entitled(db_session) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="dep-paid-1")
    db_session.add(
        CourseEntitlement(
            user_id=user.id,
            course_id=course.id,
            source=ENTITLEMENT_SOURCE_PURCHASE,
        )
    )
    await db_session.flush()

    app = _build_app(db_session, user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get(f"/courses/{course.id}/probe")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_require_course_access_403_when_not_entitled(
    db_session,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(
        db_session, slug="dep-paid-2", price_cents=9900
    )

    app = _build_app(db_session, user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get(f"/courses/{course.id}/probe")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Course not unlocked"


@pytest.mark.asyncio
async def test_require_course_access_200_for_free_course_without_row(
    db_session,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(
        db_session, slug="dep-free", price_cents=0, is_published=True
    )

    app = _build_app(db_session, user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get(f"/courses/{course.id}/probe")

    assert resp.status_code == 200
