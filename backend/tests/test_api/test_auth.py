"""Auth API tests — Batch 1 contract.

D-B: register always 202; neutral message.
D-D: password must be ≥12 chars.
D-C: login checks is_verified (grandfathered users skip gate via direct DB write).

Note: the test DB is SQLite which lacks the auth_tokens table (added in migration
0068 which only runs on Postgres). Token-flow tests (verify-email, password-reset)
are covered in test_services/test_auth_token_*.py against the Postgres container.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

REGISTER_PAYLOAD = {
    "email": "test@example.com",
    "full_name": "Test User",
    "password": "supersecret123",  # D-D: ≥12 chars
}


@pytest.mark.asyncio
async def test_register_returns_202_with_neutral_message(client: AsyncClient) -> None:
    """D-B: register always returns 202 with a neutral message."""
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 202
    data = resp.json()
    assert "message" in data
    assert "hashed_password" not in data
    assert "id" not in data


@pytest.mark.asyncio
async def test_register_duplicate_email_still_202(client: AsyncClient) -> None:
    """D-B: duplicate registration must also return 202 (no enumeration)."""
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_register_short_password_rejected(client: AsyncClient) -> None:
    """D-D: passwords shorter than 12 chars are rejected with 422."""
    payload = {**REGISTER_PAYLOAD, "password": "short123"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_with_whatsapp_number(client: AsyncClient) -> None:
    """D16/CP3.1 — optional whatsapp_number accepted, response is 202."""
    payload = {**REGISTER_PAYLOAD, "whatsapp_number": "+919876543210"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Login succeeds for a verified user.

    D-C: grandfathered users (is_verified=True) bypass the gate.
    We directly set is_verified after registration to simulate the
    migration-0069 grandfather path.
    """
    from sqlalchemy import select

    from app.models.user import User

    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    # Bypass email verification by mutating the ORM object directly in the
    # shared session (mirrors migration 0069 grandfather UPDATE).
    result = await db_session.execute(
        select(User).where(User.email == REGISTER_PAYLOAD["email"])
    )
    user = result.scalar_one()
    user.is_verified = True
    await db_session.flush()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_unverified_user_blocked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A2: login gate — unverified users get 403.

    We create an unverified user directly via the ORM (bypassing the
    autouse _auto_verify_registered_users fixture which patches
    AuthService.register to auto-verify).
    """
    from sqlalchemy import select

    from app.core.hashing import hash_password
    from app.models.user import User

    user = User(
        email=REGISTER_PAYLOAD["email"],
        full_name=REGISTER_PAYLOAD["full_name"],
        hashed_password=hash_password(REGISTER_PAYLOAD["password"]),
        role="student",
        is_verified=False,
    )
    db_session.add(user)
    await db_session.flush()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "wrongpassword123"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "x"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, db_session: AsyncSession) -> None:
    from sqlalchemy import select

    from app.models.user import User

    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    result = await db_session.execute(
        select(User).where(User.email == REGISTER_PAYLOAD["email"])
    )
    user = result.scalar_one()
    user.is_verified = True
    await db_session.flush()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    token = login.json()["access_token"]
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == REGISTER_PAYLOAD["email"]


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer bad.token.here"})
    assert resp.status_code == 401
