"""Route tests for /api/v1/today/summary and /api/v1/today/session/step/{step}."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Today Tester",
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
    resp = await client.get("/api/v1/today/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_summary_returns_full_schema_for_blank_user(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "summary@test.dev")
    resp = await client.get(
        "/api/v1/today/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_keys = {
        "user",
        "goal",
        "consistency",
        "progress",
        "session",
        "current_focus",
        "capstone",
        "next_milestone",
        "readiness",
        "intention",
        "due_card_count",
        "peers_at_level",
        "promotions_today",
        "micro_wins",
        "cohort_events",
    }
    assert expected_keys.issubset(body.keys())

    assert body["user"]["first_name"] == "Today"
    assert body["consistency"]["window_days"] == 7
    assert body["consistency"]["days_active"] >= 0
    assert body["progress"]["lessons_total"] == 0
    # GET summary is now READ-ONLY: it projects the next session ordinal
    # without writing a row. id is null until the user marks a step.
    assert body["session"]["ordinal"] == 1
    assert body["session"]["id"] is None
    assert body["due_card_count"] == 0
    assert body["micro_wins"] == []
    assert body["cohort_events"] == []


@pytest.mark.asyncio
async def test_get_summary_does_not_create_session_rows(
    client: AsyncClient,
) -> None:
    """Two consecutive GETs must not insert phantom session rows."""
    token = await _register_and_login(client, "no-phantom@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    first = await client.get("/api/v1/today/summary", headers=headers)
    second = await client.get("/api/v1/today/summary", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session"]["id"] is None
    assert second.json()["session"]["id"] is None
    # Ordinal stays at 1 — no writes happened.
    assert first.json()["session"]["ordinal"] == 1
    assert second.json()["session"]["ordinal"] == 1


@pytest.mark.asyncio
async def test_session_step_warmup_surfaces_in_summary(
    client: AsyncClient,
) -> None:
    """Warmup opens session #1, stamps warmup_done_at, leaves session open.
    The route returns the JUST-STAMPED row (not a re-projection).
    """
    token = await _register_and_login(client, "step-w@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/v1/today/session/step/warmup", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session"]["ordinal"] == 1
    assert body["session"]["id"] is not None
    assert body["session"]["warmup_done_at"] is not None
    assert body["session"]["lesson_done_at"] is None
    assert body["session"]["reflect_done_at"] is None


@pytest.mark.asyncio
async def test_session_step_reflect_returns_just_stamped_session(
    client: AsyncClient,
) -> None:
    """Reflect on session #1 closes it; the response shows session #1 with
    reflect_done_at populated (NOT a freshly-opened #2).
    """
    token = await _register_and_login(client, "step-r@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    after_reflect = await client.post(
        "/api/v1/today/session/step/reflect", headers=headers
    )
    assert after_reflect.status_code == 200, after_reflect.text
    body = after_reflect.json()
    assert body["session"]["ordinal"] == 1
    assert body["session"]["reflect_done_at"] is not None

    # A subsequent GET projects ordinal #2 (read-only — no row inserted yet).
    follow = await client.get("/api/v1/today/summary", headers=headers)
    assert follow.status_code == 200
    follow_body = follow.json()
    assert follow_body["session"]["ordinal"] == 2
    assert follow_body["session"]["id"] is None


@pytest.mark.asyncio
async def test_session_step_invalid_returns_400(client: AsyncClient) -> None:
    token = await _register_and_login(client, "bad-step@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/v1/today/session/step/notathing", headers=headers
    )
    assert resp.status_code == 400
    assert "invalid step" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_session_step_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/today/session/step/warmup")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_summary_session_ordinal_increments_after_repeat_reflects(
    client: AsyncClient,
) -> None:
    """Two reflect cycles produce strictly-increasing ordinals on the
    JUST-STAMPED session each time. After the first reflect closes #1,
    the next reflect call opens session #2 then stamps it.
    """
    token = await _register_and_login(client, "ord@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/api/v1/today/session/step/reflect", headers=headers
    )
    first_ord = first.json()["session"]["ordinal"]

    second = await client.post(
        "/api/v1/today/session/step/reflect", headers=headers
    )
    second_ord = second.json()["session"]["ordinal"]

    assert first_ord == 1
    assert second_ord == 2
