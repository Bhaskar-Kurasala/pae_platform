"""Tests for the conversation Markdown export endpoint (P1-9).

Covers:
  - auth required (401)
  - another user's conversation → 404
  - empty conversation → 200 with a valid (mostly empty) transcript
  - populated conversation → markdown contains title, both role labels,
    ISO timestamps and correctly-shaped `Content-Disposition`
  - invalid `format=xml` → 400
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

    with (
        patch("app.core.database.AsyncSessionLocal", session_factory),
        patch("app.api.v1.routes.stream.AsyncSessionLocal", session_factory),
    ):
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


async def _register_and_login(
    client: AsyncClient, email: str, *, role: str = "student"
) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Test User",
            "password": "pass1234",
            "role": role,
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


@pytest.mark.asyncio
async def test_export_requires_auth(client: AsyncClient) -> None:
    bogus_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/chat/conversations/{bogus_id}/export?format=md")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_export_other_users_conversation_returns_404(
    client: AsyncClient,
) -> None:
    alice_token = await _register_and_login(client, "alice_export@example.com")
    bob_token = await _register_and_login(client, "bob_export@example.com")

    create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Alice's thread"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    alice_conv = create.json()["id"]

    resp = await client.get(
        f"/api/v1/chat/conversations/{alice_conv}/export?format=md",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_empty_conversation_returns_minimal_transcript(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "empty_export@example.com")
    create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Quiet thread"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = create.json()["id"]

    resp = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/export?format=md",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    disp = resp.headers["content-disposition"]
    assert disp.startswith("attachment; filename=")
    assert disp.endswith(".md\"")

    body = resp.text
    assert body.startswith("# Quiet thread")
    assert "Exported: " in body
    assert "Messages: 0" in body
    # No role headers should be present for an empty transcript.
    assert "## You" not in body
    assert "## Tutor" not in body


@pytest.mark.asyncio
async def test_export_populated_conversation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "populated_export@example.com")

    # Create via the stream endpoint so we get a real user + assistant pair.
    class _FakeChunk:
        def __init__(self, t: str) -> None:
            self.content = t

    class _FakeLLM:
        async def astream(self, _msgs: list[object]):  # type: ignore[no-untyped-def]
            for t in ["Hello", " student"]:
                yield _FakeChunk(t)

    with patch("app.api.v1.routes.stream.build_llm", return_value=_FakeLLM()):
        stream_resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "what is RAG?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in stream_resp.aiter_bytes():
            pass

    list_resp = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = list_resp.json()[0]["id"]

    resp = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/export?format=md",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.text
    # Title derived from first user message.
    assert "# what is RAG?" in body
    # Both role labels.
    assert "## You" in body
    assert "## Tutor" in body
    # User content + assistant content.
    assert "what is RAG?" in body
    assert "Hello student" in body
    # A timestamp-ish line (YYYY-MM-DD HH:MM format) appears on a role header.
    # Just check the header-with-dot-separator shape:
    assert " · " in body
    # Filename includes short-id and a YYYYMMDD date slug.
    disp = resp.headers["content-disposition"]
    assert conv_id.replace("-", "")[:8] in disp


@pytest.mark.asyncio
async def test_export_rejects_unsupported_format(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fmt_export@example.com")
    create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "fmt probe"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = create.json()["id"]

    resp = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/export?format=xml",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "xml" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_defaults_to_md_when_format_missing(
    client: AsyncClient,
) -> None:
    """`format` query param defaults to 'md' — absence is not a 400."""
    token = await _register_and_login(client, "default_fmt@example.com")
    create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "default fmt"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = create.json()["id"]

    resp = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
