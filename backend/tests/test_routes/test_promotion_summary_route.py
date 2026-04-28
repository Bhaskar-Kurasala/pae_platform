"""Route tests for /api/v1/promotion/summary and /api/v1/promotion/confirm."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Promotion Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


@pytest.mark.asyncio
async def test_summary_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/promotion/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_summary_returns_full_schema(client: AsyncClient) -> None:
    token = await _register_and_login(client, "promo-route@test.dev")
    resp = await client.get(
        "/api/v1/promotion/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_keys = {
        "overall_progress",
        "rungs",
        "role",
        "stats",
        "gate_status",
        "promoted_at",
        "promoted_to_role",
        "user_first_name",
    }
    assert expected_keys.issubset(body.keys())
    assert len(body["rungs"]) == 4
    assert body["gate_status"] in {"not_ready", "ready_to_promote", "promoted"}


@pytest.mark.asyncio
async def test_confirm_409_when_gate_locked(client: AsyncClient) -> None:
    token = await _register_and_login(client, "promo-confirm@test.dev")
    resp = await client.post(
        "/api/v1/promotion/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "gate" in resp.json()["detail"].lower()
