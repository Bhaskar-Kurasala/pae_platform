"""Route tests for /api/v1/path/summary."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Path Tester",
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
async def test_path_summary_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/path/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_path_summary_returns_full_schema_for_blank_user(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "path-route@test.dev")
    resp = await client.get(
        "/api/v1/path/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_keys = {
        "overall_progress",
        "active_course_id",
        "active_course_title",
        "constellation",
        "levels",
        "proof_wall",
    }
    assert expected_keys.issubset(body.keys())
    # Constellation always has 6 stars (5 roles + goal).
    assert len(body["constellation"]) == 6
    assert body["constellation"][-1]["state"] == "goal"
    # Even for a blank user the goal rung is included in levels.
    assert any(level["state"] == "goal" for level in body["levels"])
