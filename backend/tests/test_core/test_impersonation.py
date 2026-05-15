"""Impersonation dependency — admin "view as student" contract.

Tests the get_view_target_user dependency in isolation by mounting it
on a tiny throwaway FastAPI app. This avoids depending on any specific
route's behavior and exercises the dependency's exact contract.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.impersonation import (
    IMPERSONATION_HEADER,
    get_view_target_user,
)
from app.core.security import get_current_user
from app.models.admin_audit_log import AdminAuditLog
from app.models.user import User
from sqlalchemy import select


def _build_app(db_session, principal: User):
    app = FastAPI()

    async def _override_db():
        yield db_session

    async def _override_user():
        return principal

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    @app.get("/whoami")
    async def whoami(user: User = Depends(get_view_target_user)):
        return {"id": str(user.id), "email": user.email}

    return app


@pytest.fixture
async def admin_and_student(db_session):
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@test.dev",
        full_name="Admin",
        hashed_password="x",
        role="admin",
        is_verified=True,
        is_active=True,
    )
    student = User(
        email=f"student-{uuid.uuid4().hex[:8]}@test.dev",
        full_name="Student",
        hashed_password="x",
        role="student",
        is_verified=True,
        is_active=True,
    )
    db_session.add_all([admin, student])
    await db_session.flush()
    return admin, student


@pytest.mark.asyncio
async def test_no_header_returns_caller(db_session, admin_and_student):
    admin, _ = admin_and_student
    app = _build_app(db_session, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get("/whoami")
    assert res.status_code == 200
    assert res.json()["email"] == admin.email


@pytest.mark.asyncio
async def test_admin_with_header_returns_target(db_session, admin_and_student):
    admin, student = admin_and_student
    app = _build_app(db_session, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(
            "/whoami", headers={IMPERSONATION_HEADER: str(student.id)}
        )
    assert res.status_code == 200
    assert res.json()["email"] == student.email


@pytest.mark.asyncio
async def test_non_admin_with_header_is_forbidden(db_session, admin_and_student):
    admin, student = admin_and_student
    # Caller is the student trying to impersonate admin.
    app = _build_app(db_session, student)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(
            "/whoami", headers={IMPERSONATION_HEADER: str(admin.id)}
        )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_malformed_target_id_is_400(db_session, admin_and_student):
    admin, _ = admin_and_student
    app = _build_app(db_session, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get("/whoami", headers={IMPERSONATION_HEADER: "not-a-uuid"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_unknown_target_is_404(db_session, admin_and_student):
    admin, _ = admin_and_student
    app = _build_app(db_session, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(
            "/whoami", headers={IMPERSONATION_HEADER: str(uuid.uuid4())}
        )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_successful_impersonation_emits_audit_row(
    db_session, admin_and_student
):
    admin, student = admin_and_student
    app = _build_app(db_session, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(
            "/whoami", headers={IMPERSONATION_HEADER: str(student.id)}
        )
    assert res.status_code == 200

    rows = (
        await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action_type == "impersonate_view"
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    row = rows[-1]
    assert row.admin_id == admin.id
    assert row.resource_id == str(student.id)
    assert row.resource_type == "user"
