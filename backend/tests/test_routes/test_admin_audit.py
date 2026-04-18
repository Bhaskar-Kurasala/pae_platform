"""Tests for admin audit-log endpoint (#142)."""

import pytest
from httpx import AsyncClient


async def _admin_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "auditadmin@example.com",
            "full_name": "Audit Admin",
            "password": "admin1234",
            "role": "admin",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "auditadmin@example.com", "password": "admin1234"},
    )
    return str(resp.json()["access_token"])


async def _student_token(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "auditstudent@example.com",
            "full_name": "Audit Student",
            "password": "pass1234",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "auditstudent@example.com", "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


@pytest.mark.asyncio
async def test_audit_log_requires_admin(client: AsyncClient) -> None:
    token = await _student_token(client)
    resp = await client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_returns_list(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_audit_log_pagination(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.get(
        "/api/v1/admin/audit-log",
        params={"limit": 5, "offset": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) <= 5


@pytest.mark.asyncio
async def test_audit_log_item_shape(client: AsyncClient) -> None:
    """If there are items, each must have the expected keys."""
    token = await _admin_token(client)
    resp = await client.get(
        "/api/v1/admin/audit-log",
        params={"limit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()
    if items:
        item = items[0]
        for key in ("id", "agent_name", "action_type", "status", "created_at"):
            assert key in item, f"Missing key: {key}"
