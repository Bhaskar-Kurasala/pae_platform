"""Tests for the P1-5 chat-feedback surface.

Covers:
  - auth required
  - create feedback → fetch → upsert-replaces (same user, same message)
  - ownership 404 (cross-user probing)
  - invalid payload 422
  - cascade test: deleting a message cascades the feedback row
  - unique constraint: two feedback rows for (message_id, user_id) impossible
  - inline `my_feedback` on `GET /conversations/{id}` after rating
  - admin rollup endpoint aggregates up/down counts + top reasons
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
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
    """Per-test FastAPI client against an in-memory SQLite engine."""
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


class _FakeChunk:
    def __init__(self, text: str) -> None:
        self.content = text


class _FakeLLM:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def astream(self, messages: list[Any]) -> AsyncIterator[_FakeChunk]:
        for t in self._tokens:
            yield _FakeChunk(t)


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


async def _seed_conversation_with_assistant(
    client: AsyncClient, token: str, *, tokens: list[str] | None = None
) -> tuple[str, str]:
    """Stream one turn and return (conversation_id, assistant_message_id)."""
    fake_llm = _FakeLLM(tokens or ["Hello", " there"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "seed question"},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp.aiter_bytes():
            pass

    list_resp = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = list_resp.json()[0]["id"]

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assistant = next(
        m for m in detail.json()["messages"] if m["role"] == "assistant"
    )
    return conv_id, assistant["id"]


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feedback_requires_auth(client: AsyncClient) -> None:
    fake_msg = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/chat/messages/{fake_msg}/feedback",
        json={"rating": "up"},
    )
    assert resp.status_code == 401

    get_resp = await client.get(f"/api/v1/chat/messages/{fake_msg}/feedback")
    assert get_resp.status_code == 401


@pytest.mark.asyncio
async def test_submit_feedback_thumbs_up_and_fetch(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fb_up@example.com")
    _, msg_id = await _seed_conversation_with_assistant(client, token)

    post = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"rating": "up"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert post.status_code == 200
    body = post.json()
    assert body["rating"] == "up"
    assert body["reasons"] is None
    assert body["comment"] is None
    assert body["message_id"] == msg_id
    uuid.UUID(body["id"])

    # Fetch returns the same row.
    got = await client.get(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]
    assert got.json()["rating"] == "up"


@pytest.mark.asyncio
async def test_submit_feedback_upsert_replaces(client: AsyncClient) -> None:
    """Re-rating the same message overwrites the earlier row (no duplicates)."""
    token = await _register_and_login(client, "fb_upsert@example.com")
    _, msg_id = await _seed_conversation_with_assistant(client, token)

    first = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"rating": "up"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    second = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={
            "rating": "down",
            "reasons": ["incorrect", "unhelpful"],
            "comment": "Way off base",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    second_body = second.json()
    # Same primary key — it's an update, not an insert.
    assert second_body["id"] == first_id
    assert second_body["rating"] == "down"
    assert second_body["reasons"] == ["incorrect", "unhelpful"]
    assert second_body["comment"] == "Way off base"


@pytest.mark.asyncio
async def test_feedback_ownership_returns_404(client: AsyncClient) -> None:
    """Bob cannot post/get feedback on Alice's message — 404, not 403."""
    alice_token = await _register_and_login(client, "fb_alice@example.com")
    bob_token = await _register_and_login(client, "fb_bob@example.com")

    _, alice_msg_id = await _seed_conversation_with_assistant(client, alice_token)

    post = await client.post(
        f"/api/v1/chat/messages/{alice_msg_id}/feedback",
        json={"rating": "up"},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert post.status_code == 404

    get = await client.get(
        f"/api/v1/chat/messages/{alice_msg_id}/feedback",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert get.status_code == 404

    # Random / nonexistent id also 404.
    ghost = await client.post(
        f"/api/v1/chat/messages/{uuid.uuid4()}/feedback",
        json={"rating": "up"},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert ghost.status_code == 404


@pytest.mark.asyncio
async def test_feedback_invalid_rating_returns_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fb_invalid@example.com")
    _, msg_id = await _seed_conversation_with_assistant(client, token)

    bad_rating = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"rating": "maybe"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bad_rating.status_code == 422

    # Missing rating entirely.
    missing = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"reasons": ["incorrect"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 422

    # Oversized comment.
    over = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"rating": "down", "comment": "x" * 2001},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert over.status_code == 422


@pytest.mark.asyncio
async def test_feedback_cascade_on_conversation_delete(client: AsyncClient) -> None:
    """Deleting the parent conversation wipes the feedback row as well."""
    token = await _register_and_login(client, "fb_cascade@example.com")
    conv_id, msg_id = await _seed_conversation_with_assistant(client, token)

    await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"rating": "up"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Hard-delete the conversation → cascades to messages → cascades to feedback.
    delete = await client.delete(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete.status_code == 204

    # The message + its feedback are gone; probing returns 404.
    gone = await client.get(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_feedback_inline_on_get_conversation(client: AsyncClient) -> None:
    """After rating, `GET /conversations/{id}` inlines `my_feedback` on the row."""
    token = await _register_and_login(client, "fb_inline@example.com")
    conv_id, msg_id = await _seed_conversation_with_assistant(client, token)

    await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"rating": "down", "reasons": ["unsafe"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    messages = detail.json()["messages"]
    rated = next(m for m in messages if m["id"] == msg_id)
    assert rated["my_feedback"] is not None
    assert rated["my_feedback"]["rating"] == "down"
    assert rated["my_feedback"]["reasons"] == ["unsafe"]

    # User-role rows have no feedback hydrated.
    user_row = next(m for m in messages if m["role"] == "user")
    assert user_row["my_feedback"] is None


@pytest.mark.asyncio
async def test_admin_feedback_rollup(client: AsyncClient) -> None:
    """Admin rollup returns up/down counts + top reasons across the window."""
    admin_token = await _register_and_login(
        client, "fb_admin@example.com", role="admin"
    )
    student_token = await _register_and_login(client, "fb_student@example.com")

    _, msg1 = await _seed_conversation_with_assistant(client, student_token)
    _, msg2 = await _seed_conversation_with_assistant(
        client, student_token, tokens=["other", " reply"]
    )

    await client.post(
        f"/api/v1/chat/messages/{msg1}/feedback",
        json={"rating": "up"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    await client.post(
        f"/api/v1/chat/messages/{msg2}/feedback",
        json={"rating": "down", "reasons": ["incorrect"], "comment": "meh"},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    resp = await client.get(
        "/api/v1/admin/chat-feedback?since_days=30",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["up_count"] == 1
    assert data["down_count"] == 1
    reasons = {r["reason"]: r["count"] for r in data["top_reasons"]}
    assert reasons.get("incorrect") == 1
    assert "meh" in data["sample_comments"]

    # Student is blocked.
    forbidden = await client.get(
        "/api/v1/admin/chat-feedback",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert forbidden.status_code == 403
