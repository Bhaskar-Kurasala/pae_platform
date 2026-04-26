"""Route tests for /api/v1/readiness/events*."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Workspace Tester",
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
async def test_post_single_event_returns_recorded_one(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "ws-single@test.dev")
    resp = await client.post(
        "/api/v1/readiness/events",
        headers={"Authorization": f"Bearer {token}"},
        json={"view": "overview", "event": "view_opened"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recorded"] == 1
    assert body["skipped"] == 0


@pytest.mark.asyncio
async def test_post_batch_reports_recorded_and_skipped(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "ws-batch@test.dev")
    resp = await client.post(
        "/api/v1/readiness/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {"view": "overview", "event": "view_opened"},
                {"view": "kit", "event": "kit_build_started"},
                {
                    "view": "resume",
                    "event": "cta_clicked",
                    "payload": {"button": "tailor"},
                },
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # All three are well-formed and pass the service-layer guard.
    assert body["recorded"] == 3
    assert body["skipped"] == 0


@pytest.mark.asyncio
async def test_post_without_auth_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/readiness/events",
        json={"view": "overview", "event": "view_opened"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_requires_auth_and_is_user_scoped(
    client: AsyncClient,
) -> None:
    # No auth → 401.
    resp_unauth = await client.get("/api/v1/readiness/events")
    assert resp_unauth.status_code == 401

    # User A writes two events.
    token_a = await _register_and_login(client, "ws-scoped-a@test.dev")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    await client.post(
        "/api/v1/readiness/events",
        headers=headers_a,
        json={
            "events": [
                {"view": "overview", "event": "view_opened"},
                {"view": "resume", "event": "cta_clicked"},
            ]
        },
    )

    # User B sees nothing of User A's.
    token_b = await _register_and_login(client, "ws-scoped-b@test.dev")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    resp_b = await client.get(
        "/api/v1/readiness/events", headers=headers_b
    )
    assert resp_b.status_code == 200
    assert resp_b.json() == []

    # User A sees its own.
    resp_a = await client.get(
        "/api/v1/readiness/events", headers=headers_a
    )
    assert resp_a.status_code == 200
    rows_a = resp_a.json()
    assert len(rows_a) == 2
    assert {r["view"] for r in rows_a} == {"overview", "resume"}


@pytest.mark.asyncio
async def test_summary_returns_expected_shape(client: AsyncClient) -> None:
    token = await _register_and_login(client, "ws-summary@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/api/v1/readiness/events",
        headers=headers,
        json={
            "events": [
                {"view": "overview", "event": "view_opened"},
                {"view": "overview", "event": "cta_clicked"},
                {"view": "kit", "event": "kit_build_started"},
            ]
        },
    )

    resp = await client.get(
        "/api/v1/readiness/events/summary", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "total",
        "by_view",
        "by_event",
        "last_event_at",
        "since_days",
        "generated_at",
    }
    assert body["total"] == 3
    assert body["by_view"] == {"overview": 2, "kit": 1}
    assert body["by_event"] == {
        "view_opened": 1,
        "cta_clicked": 1,
        "kit_build_started": 1,
    }
    assert body["since_days"] == 7
    assert body["last_event_at"] is not None


@pytest.mark.asyncio
async def test_summary_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/readiness/events/summary")
    assert resp.status_code == 401
