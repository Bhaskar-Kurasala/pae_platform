"""Route tests for /api/v1/chat/welcome-prompts (Tutor refactor 2026-04-26)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Welcome Tester",
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
async def test_welcome_prompts_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/chat/welcome-prompts")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_welcome_prompts_default_mode_returns_fallback(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "wp-default@test.dev")
    resp = await client.get(
        "/api/v1/chat/welcome-prompts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "auto"
    assert isinstance(body["prompts"], list)
    assert len(body["prompts"]) >= 1
    # Each prompt has the expected shape.
    for p in body["prompts"]:
        assert {"text", "icon", "kind", "rationale"}.issubset(p.keys())


@pytest.mark.asyncio
async def test_welcome_prompts_mode_tutor_returns_tutor_or_auto_kinds(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "wp-tutor@test.dev")
    resp = await client.get(
        "/api/v1/chat/welcome-prompts?mode=tutor",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "tutor"
    assert len(body["prompts"]) >= 1
    for p in body["prompts"]:
        assert p["kind"] in {"tutor", "auto"}


@pytest.mark.asyncio
async def test_welcome_prompts_invalid_mode_coerced_to_auto(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "wp-bad@test.dev")
    resp = await client.get(
        "/api/v1/chat/welcome-prompts?mode=garbage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "auto"
    assert len(body["prompts"]) >= 1


@pytest.mark.asyncio
async def test_welcome_prompts_capped_at_six(client: AsyncClient) -> None:
    token = await _register_and_login(client, "wp-cap@test.dev")
    resp = await client.get(
        "/api/v1/chat/welcome-prompts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["prompts"]) <= 6
