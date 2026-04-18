from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Reflection Tester",
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
async def test_get_today_returns_null_when_missing(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_missing@example.com")
    resp = await client.get(
        "/api/v1/reflections/me/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_create_reflection_today(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_create@example.com")
    payload = {"mood": "steady", "note": "Shipped the login flow."}
    resp = await client.post(
        "/api/v1/reflections/me",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["mood"] == "steady"
    assert data["note"] == "Shipped the login flow."
    assert data["reflection_date"] == datetime.now(UTC).date().isoformat()
    assert "id" in data


@pytest.mark.asyncio
async def test_upsert_same_day_updates(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_upsert@example.com")
    first = {"mood": "meh", "note": "Stuck on retrieval eval."}
    resp1 = await client.post(
        "/api/v1/reflections/me",
        json=first,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 201
    id_1 = resp1.json()["id"]

    second = {"mood": "flowing", "note": "Fixed it — cosine vs dot product."}
    resp2 = await client.post(
        "/api/v1/reflections/me",
        json=second,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200  # updated, not created
    data = resp2.json()
    assert data["id"] == id_1
    assert data["mood"] == "flowing"
    assert data["note"].startswith("Fixed it")


@pytest.mark.asyncio
async def test_get_today_after_create(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_get@example.com")
    await client.post(
        "/api/v1/reflections/me",
        json={"mood": "blocked", "note": "Docker compose won't start."},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get(
        "/api/v1/reflections/me/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data is not None
    assert data["mood"] == "blocked"


@pytest.mark.asyncio
async def test_create_backdated_reflection(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_backdate@example.com")
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    resp = await client.post(
        "/api/v1/reflections/me",
        json={
            "mood": "steady",
            "note": "Yesterday's entry.",
            "reflection_date": yesterday,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["reflection_date"] == yesterday
    # Today still has nothing logged.
    today_resp = await client.get(
        "/api/v1/reflections/me/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert today_resp.json() is None


@pytest.mark.asyncio
async def test_list_recent_reflections(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_list@example.com")
    today = datetime.now(UTC).date()
    for i in range(3):
        day = (today - timedelta(days=i)).isoformat()
        await client.post(
            "/api/v1/reflections/me",
            json={"mood": "steady", "note": f"Day {i}", "reflection_date": day},
            headers={"Authorization": f"Bearer {token}"},
        )
    resp = await client.get(
        "/api/v1/reflections/me/recent?limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    # Newest first
    assert rows[0]["reflection_date"] == today.isoformat()


@pytest.mark.asyncio
async def test_mood_enum_validation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_enum@example.com")
    resp = await client.post(
        "/api/v1/reflections/me",
        json={"mood": "ecstatic", "note": "Not a valid mood."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_note_max_length(client: AsyncClient) -> None:
    token = await _register_and_login(client, "refl_length@example.com")
    resp = await client.post(
        "/api/v1/reflections/me",
        json={"mood": "meh", "note": "x" * 281},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reflections_require_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/reflections/me/today")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reflections_are_per_user(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "refl_a@example.com")
    token_b = await _register_and_login(client, "refl_b@example.com")

    await client.post(
        "/api/v1/reflections/me",
        json={"mood": "flowing", "note": "User A's note."},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = await client.get(
        "/api/v1/reflections/me/today",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 200
    assert resp_b.json() is None  # B has none
