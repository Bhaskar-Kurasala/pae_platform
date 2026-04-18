"""API tests for spaced-repetition endpoints (P2-05)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "SRS Tester",
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
async def test_create_card_and_list_due(client: AsyncClient) -> None:
    token = await _register_and_login(client, "srs1@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    # New card is due immediately (next_due_at = now).
    create = await client.post(
        "/api/v1/srs/cards",
        headers=headers,
        json={"concept_key": "rag-basics", "prompt": "What is retrieval-augmented generation?"},
    )
    assert create.status_code == 201
    card = create.json()
    assert card["concept_key"] == "rag-basics"
    assert card["repetitions"] == 0
    assert card["interval_days"] == 0

    due = await client.get("/api/v1/srs/due", headers=headers)
    assert due.status_code == 200
    items = due.json()
    assert len(items) == 1
    assert items[0]["concept_key"] == "rag-basics"


@pytest.mark.asyncio
async def test_review_advances_interval_and_removes_from_due(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "srs2@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/srs/cards",
        headers=headers,
        json={"concept_key": "langgraph-edges", "prompt": "Conditional edges?"},
    )
    card_id = create.json()["id"]

    review = await client.post(
        f"/api/v1/srs/cards/{card_id}/review",
        headers=headers,
        json={"quality": 5},
    )
    assert review.status_code == 200
    body = review.json()
    assert body["repetitions"] == 1
    assert body["interval_days"] == 1

    # Now that next_due_at is ~1 day in the future, due list should be empty.
    due = await client.get("/api/v1/srs/due", headers=headers)
    assert due.json() == []


@pytest.mark.asyncio
async def test_review_wrong_answer_resets(client: AsyncClient) -> None:
    token = await _register_and_login(client, "srs3@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/srs/cards",
        headers=headers,
        json={"concept_key": "pydantic-v2", "prompt": "model_validate vs model_dump"},
    )
    card_id = create.json()["id"]

    # Two good reviews first to build up state.
    await client.post(
        f"/api/v1/srs/cards/{card_id}/review",
        headers=headers,
        json={"quality": 5},
    )
    await client.post(
        f"/api/v1/srs/cards/{card_id}/review",
        headers=headers,
        json={"quality": 4},
    )
    # Now fail.
    fail = await client.post(
        f"/api/v1/srs/cards/{card_id}/review",
        headers=headers,
        json={"quality": 1},
    )
    body = fail.json()
    assert body["repetitions"] == 0
    assert body["interval_days"] == 1


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_duplicate_concept_key(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "srs4@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    a = await client.post(
        "/api/v1/srs/cards",
        headers=headers,
        json={"concept_key": "same-key", "prompt": "first"},
    )
    b = await client.post(
        "/api/v1/srs/cards",
        headers=headers,
        json={"concept_key": "same-key", "prompt": "second"},
    )
    # Same id returned — not a duplicate row.
    assert a.json()["id"] == b.json()["id"]


@pytest.mark.asyncio
async def test_review_rejects_quality_out_of_range(client: AsyncClient) -> None:
    token = await _register_and_login(client, "srs5@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/srs/cards",
        headers=headers,
        json={"concept_key": "embeddings-101"},
    )
    card_id = create.json()["id"]

    resp = await client.post(
        f"/api/v1/srs/cards/{card_id}/review",
        headers=headers,
        json={"quality": 9},
    )
    assert resp.status_code == 422  # Pydantic ge/le rejection


@pytest.mark.asyncio
async def test_review_nonexistent_card_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "srs6@test.dev")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/srs/cards/00000000-0000-0000-0000-000000000000/review",
        headers=headers,
        json={"quality": 3},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_srs_endpoints_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/srs/due")).status_code == 401
    assert (
        await client.post("/api/v1/srs/cards", json={"concept_key": "x"})
    ).status_code == 401


@pytest.mark.asyncio
async def test_cards_are_scoped_to_owning_user(client: AsyncClient) -> None:
    t1 = await _register_and_login(client, "srs-a@test.dev")
    t2 = await _register_and_login(client, "srs-b@test.dev")

    await client.post(
        "/api/v1/srs/cards",
        headers={"Authorization": f"Bearer {t1}"},
        json={"concept_key": "user-a-card"},
    )

    # User B sees nothing.
    due = await client.get(
        "/api/v1/srs/due",
        headers={"Authorization": f"Bearer {t2}"},
    )
    assert due.json() == []
