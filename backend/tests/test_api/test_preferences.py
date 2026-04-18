"""API tests for user preferences (P2-02)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Prefs Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_get_preferences_returns_defaults(client: AsyncClient) -> None:
    token = await _register_and_login(client, "prefs1@test.dev")
    resp = await client.get(
        "/api/v1/preferences/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"tutor_mode": "standard", "ugly_draft_mode": False, "socratic_level": 0}


@pytest.mark.asyncio
async def test_patch_tutor_mode_to_socratic_strict(client: AsyncClient) -> None:
    token = await _register_and_login(client, "prefs2@test.dev")
    resp = await client.patch(
        "/api/v1/preferences/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"tutor_mode": "socratic_strict"},
    )
    assert resp.status_code == 200
    assert resp.json()["tutor_mode"] == "socratic_strict"

    # Read back
    resp = await client.get(
        "/api/v1/preferences/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["tutor_mode"] == "socratic_strict"


@pytest.mark.asyncio
async def test_patch_rejects_unknown_tutor_mode(client: AsyncClient) -> None:
    token = await _register_and_login(client, "prefs3@test.dev")
    resp = await client.patch(
        "/api/v1/preferences/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"tutor_mode": "bogus"},
    )
    # Pydantic Literal rejects at request validation → 422
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_ugly_draft_mode_only(client: AsyncClient) -> None:
    token = await _register_and_login(client, "prefs4@test.dev")
    resp = await client.patch(
        "/api/v1/preferences/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"ugly_draft_mode": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ugly_draft_mode"] is True
    assert body["tutor_mode"] == "standard"  # untouched


@pytest.mark.asyncio
async def test_preferences_require_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/preferences/me")
    assert resp.status_code == 401
