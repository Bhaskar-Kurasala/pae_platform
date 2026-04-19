"""Tests for the P1-8 sidebar management surface.

Covers:
  - PATCH conversation accepts `{pinned: True/False}`, stamping/clearing
    `pinned_at` and reflecting the change in `ConversationRead`.
  - GET /conversations orders pinned rows first (by `pinned_at DESC`),
    then unpinned rows by `updated_at DESC`.
  - Pinning and archiving compose cleanly: a pinned+archived row stays
    hidden by default but still pins to the top of `include_archived=true`.
  - `?q=` continues to passthrough against title + content search while
    the pinned ordering is in effect.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Per-test FastAPI client backed by an in-memory SQLite engine."""
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


async def _create_conv(client: AsyncClient, token: str, title: str) -> str:
    resp = await client.post(
        "/api/v1/chat/conversations",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest.mark.asyncio
async def test_pin_toggle_stamps_and_clears_pinned_at(client: AsyncClient) -> None:
    """PATCH `{pinned: True}` sets `pinned_at`; `{pinned: False}` clears it."""
    token = await _register_and_login(client, "pin_toggle@example.com")
    conv_id = await _create_conv(client, token, "to pin")

    # Baseline — no pin.
    resp = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_at"] is None

    # Pin.
    patch = await client.patch(
        f"/api/v1/chat/conversations/{conv_id}",
        json={"pinned": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["pinned_at"] is not None

    # Unpin.
    patch2 = await client.patch(
        f"/api/v1/chat/conversations/{conv_id}",
        json={"pinned": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch2.status_code == 200
    assert patch2.json()["pinned_at"] is None


@pytest.mark.asyncio
async def test_pinned_rows_listed_first_by_pinned_at(client: AsyncClient) -> None:
    """Pinned conversations surface above non-pinned ones, pinned-at DESC."""
    token = await _register_and_login(client, "pin_order@example.com")

    # Three conversations; pin the second one first, then the third so the
    # third's pin-time is more recent. Expected final order:
    #   [3rd (pinned, newest pin), 2nd (pinned, older pin), 1st (unpinned)]
    first = await _create_conv(client, token, "first")
    second = await _create_conv(client, token, "second")
    third = await _create_conv(client, token, "third")

    for cid in (second, third):
        # Tiny yield so `pinned_at` timestamps are distinct across Postgres &
        # SQLite (the latter resolves datetimes to microseconds too, but we
        # want to be safe against clock-step-resolution weirdness).
        await asyncio.sleep(0.01)
        r = await client.patch(
            f"/api/v1/chat/conversations/{cid}",
            json={"pinned": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    list_resp = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.status_code == 200
    ids = [row["id"] for row in list_resp.json()]
    # Third (pinned last) first, then second (pinned first), then first (unpinned).
    assert ids[0] == third, ids
    assert ids[1] == second, ids
    assert ids[-1] == first, ids


@pytest.mark.asyncio
async def test_pinned_plus_archived_interaction(client: AsyncClient) -> None:
    """A pinned+archived conversation is hidden by default but leads the
    archived-inclusive list."""
    token = await _register_and_login(client, "pin_arch@example.com")

    pinned_archived = await _create_conv(client, token, "pinned+archived")
    plain = await _create_conv(client, token, "plain")

    # Pin + archive the first conversation.
    r1 = await client.patch(
        f"/api/v1/chat/conversations/{pinned_archived}",
        json={"pinned": True, "archived": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["pinned_at"] is not None
    assert body["archived_at"] is not None

    # Default list: archived row is hidden even though it's pinned.
    default = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    default_ids = [row["id"] for row in default.json()]
    assert pinned_archived not in default_ids
    assert plain in default_ids

    # include_archived=true surfaces it AND floats it to the top.
    all_resp = await client.get(
        "/api/v1/chat/conversations?include_archived=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    all_ids = [row["id"] for row in all_resp.json()]
    assert all_ids[0] == pinned_archived, all_ids


@pytest.mark.asyncio
async def test_search_query_passthrough_with_pinned_ordering(
    client: AsyncClient,
) -> None:
    """`?q=` filters against title ILIKE even when pinning is in play."""
    token = await _register_and_login(client, "pin_search@example.com")

    py = await _create_conv(client, token, "Python basics")
    rust = await _create_conv(client, token, "Rust basics")
    await _create_conv(client, token, "SQL tips")

    # Pin the Rust one so we can also verify it leads the filtered result.
    r = await client.patch(
        f"/api/v1/chat/conversations/{rust}",
        json={"pinned": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    resp = await client.get(
        "/api/v1/chat/conversations?q=basics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    # Both `basics` rows present; pinned one first; SQL tips excluded.
    assert rust in ids
    assert py in ids
    assert ids[0] == rust, ids
    assert len(ids) == 2
