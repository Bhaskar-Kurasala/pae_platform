"""Tests for the feedback widget API endpoints (#177)."""
import pytest
from httpx import AsyncClient


async def _admin_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "feedback_admin@example.com",
            "full_name": "FeedbackAdmin",
            "password": "admin1234",
            "role": "admin",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "feedback_admin@example.com", "password": "admin1234"},
    )
    return str(resp.json()["access_token"])


async def _student_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "feedback_student@example.com",
            "full_name": "FeedbackStudent",
            "password": "pass1234",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "feedback_student@example.com", "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


@pytest.mark.asyncio
async def test_submit_feedback_authenticated(client: AsyncClient) -> None:
    token = await _student_token(client)
    resp = await client.post(
        "/api/v1/feedback",
        json={
            "route": "/receipts",
            "body": "The receipts page is confusing",
            "sentiment": "negative",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data


@pytest.mark.asyncio
async def test_submit_feedback_anonymous(client: AsyncClient) -> None:
    """No auth header — should still succeed (anonymous submission)."""
    resp = await client.post(
        "/api/v1/feedback",
        json={"route": "/", "body": "Nice landing page"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data


@pytest.mark.asyncio
async def test_admin_list_feedback(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.get(
        "/api/v1/feedback/admin", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_list_requires_admin(client: AsyncClient) -> None:
    token = await _student_token(client)
    resp = await client.get(
        "/api/v1/feedback/admin", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_resolve_feedback(client: AsyncClient) -> None:
    admin_tok = await _admin_token(client)
    # Submit anonymous feedback first
    await client.post(
        "/api/v1/feedback",
        json={"route": "/", "body": "test resolve"},
    )
    # List to get the item id
    list_resp = await client.get(
        "/api/v1/feedback/admin",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    items = list_resp.json()
    assert len(items) > 0
    item_id = items[0]["id"]

    # Resolve it
    resp = await client.patch(
        f"/api/v1/feedback/admin/{item_id}/resolve",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_resolve_nonexistent(client: AsyncClient) -> None:
    token = await _admin_token(client)
    import uuid

    fake_id = uuid.uuid4()
    resp = await client.patch(
        f"/api/v1/feedback/admin/{fake_id}/resolve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
