import pytest
from httpx import AsyncClient

REGISTER_PAYLOAD = {
    "email": "test@example.com",
    "full_name": "Test User",
    "password": "secret123",
}


@pytest.mark.asyncio
async def test_register(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == REGISTER_PAYLOAD["email"]
    assert data["full_name"] == REGISTER_PAYLOAD["full_name"]
    assert "hashed_password" not in data
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_with_whatsapp_number(client: AsyncClient) -> None:
    """D16/CP3.1 — optional whatsapp_number persists and surfaces on UserResponse."""
    payload = {**REGISTER_PAYLOAD, "whatsapp_number": "+919876543210"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["whatsapp_number"] == "+919876543210"


@pytest.mark.asyncio
async def test_register_without_whatsapp_number_is_none(client: AsyncClient) -> None:
    """D16/CP3.1 — omitting whatsapp_number stores NULL (renders as None in response).

    Empty string is NOT the same as missing — the auth service explicitly
    skips the field when falsy so the DB stores NULL, not an empty string.
    """
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["whatsapp_number"] is None


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
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
async def test_login_wrong_password(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "wrongpassword"},
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
async def test_get_me(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
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
