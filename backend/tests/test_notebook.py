"""Tests for the notebook endpoints (P3-4).

Covers:
  - POST /api/v1/chat/notebook → 201 + entry body
  - GET  /api/v1/chat/notebook → list returned, newest first
  - DELETE /api/v1/chat/notebook/{id} → 204
  - DELETE /api/v1/chat/notebook/{id} non-owner → 404
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Forwarded-For": "127.0.0.1"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Test User",
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
async def test_save_to_notebook_returns_201(client: AsyncClient) -> None:
    token = await _register_and_login(client, "nb-user@test.com")
    resp = await client.post(
        "/api/v1/chat/notebook",
        json={
            "message_id": "msg-abc",
            "conversation_id": "conv-xyz",
            "content": "Generators are lazy iterators.",
            "title": "About generators",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["message_id"] == "msg-abc"
    assert data["conversation_id"] == "conv-xyz"
    assert data["content"] == "Generators are lazy iterators."
    assert data["title"] == "About generators"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_list_notebook_returns_entries(client: AsyncClient) -> None:
    token = await _register_and_login(client, "nb-list@test.com")
    auth = {"Authorization": f"Bearer {token}"}

    # Create two entries.
    for i in range(2):
        await client.post(
            "/api/v1/chat/notebook",
            json={
                "message_id": f"msg-{i}",
                "conversation_id": "conv-1",
                "content": f"Entry {i}",
            },
            headers=auth,
        )

    resp = await client.get("/api/v1/chat/notebook", headers=auth)
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert len(entries) == 2
    # Newest first — entry-1 has the later created_at.
    assert entries[0]["message_id"] == "msg-1"


@pytest.mark.asyncio
async def test_delete_notebook_entry(client: AsyncClient) -> None:
    token = await _register_and_login(client, "nb-del@test.com")
    auth = {"Authorization": f"Bearer {token}"}

    # Create entry.
    create_resp = await client.post(
        "/api/v1/chat/notebook",
        json={
            "message_id": "msg-del",
            "conversation_id": "conv-1",
            "content": "To be deleted",
        },
        headers=auth,
    )
    entry_id = create_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/chat/notebook/{entry_id}", headers=auth
    )
    assert del_resp.status_code == 204, del_resp.text

    # List should be empty now.
    list_resp = await client.get("/api/v1/chat/notebook", headers=auth)
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_notebook_entry_wrong_owner_returns_404(
    client: AsyncClient,
) -> None:
    token_a = await _register_and_login(client, "nb-owner-a@test.com")
    token_b = await _register_and_login(client, "nb-owner-b@test.com")

    # User A creates an entry.
    create_resp = await client.post(
        "/api/v1/chat/notebook",
        json={
            "message_id": "msg-private",
            "conversation_id": "conv-1",
            "content": "Private note",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    entry_id = create_resp.json()["id"]

    # User B tries to delete it.
    del_resp = await client.delete(
        f"/api/v1/chat/notebook/{entry_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_resp.status_code == 404, del_resp.text


@pytest.mark.asyncio
async def test_notebook_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/chat/notebook")
    assert resp.status_code == 401
