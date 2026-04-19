"""Tests for the persisted chat surface (P0-2).

Covers:
  - create / list / get / patch / delete conversation
  - ownership enforcement (404 for other-user conversations)
  - include_archived / search filters
  - cascade delete wipes messages
  - stream endpoint persists user + assistant turns and returns the
    conversation_id in the first SSE event
  - stream on an existing conversation appends to it
  - stream with a foreign conversation_id returns 404
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Per-test FastAPI client.

    Overrides `get_db` AND patches `AsyncSessionLocal` (used by the stream
    endpoint's setup block and by its best-effort post-stream persistence)
    so every DB access in a test hits the same in-memory SQLite engine.
    Without this, stream tests would silently miss rows because the default
    `AsyncSessionLocal` points at the prod Postgres pool.
    """
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
        patch(
            "app.core.database.AsyncSessionLocal", session_factory
        ),
        patch(
            "app.api.v1.routes.stream.AsyncSessionLocal", session_factory
        ),
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
    """Test double that yields a scripted sequence for llm.astream()."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def astream(self, messages: list[Any]) -> AsyncIterator[_FakeChunk]:
        for t in self._tokens:
            yield _FakeChunk(t)


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    """Parse an SSE body into a list of JSON event dicts."""
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :].strip()
        if not payload:
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return events


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
async def test_requires_auth(client: AsyncClient) -> None:
    """Every /api/v1/chat endpoint must be authenticated."""
    resp = await client.get("/api/v1/chat/conversations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_conversation_returns_empty_body(client: AsyncClient) -> None:
    token = await _register_and_login(client, "chat_create@example.com")
    resp = await client.post(
        "/api/v1/chat/conversations",
        json={"agent_name": "socratic_tutor", "title": "My thread"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_name"] == "socratic_tutor"
    assert data["title"] == "My thread"
    assert data["archived_at"] is None
    assert data["messages"] == []
    uuid.UUID(data["id"])  # well-formed UUID


@pytest.mark.asyncio
async def test_list_conversations_excludes_archived_by_default(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "chat_list@example.com")

    # Make three conversations.
    created_ids = []
    for idx in range(3):
        resp = await client.post(
            "/api/v1/chat/conversations",
            json={"title": f"thread {idx}"},
            headers={"Authorization": f"Bearer {token}"},
        )
        created_ids.append(resp.json()["id"])

    # Archive the middle one via PATCH.
    patch_resp = await client.patch(
        f"/api/v1/chat/conversations/{created_ids[1]}",
        json={"archived": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["archived_at"] is not None

    # Default list hides archived.
    list_resp = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.status_code == 200
    ids = {row["id"] for row in list_resp.json()}
    assert created_ids[1] not in ids
    assert {created_ids[0], created_ids[2]}.issubset(ids)

    # include_archived=true surfaces it.
    all_resp = await client.get(
        "/api/v1/chat/conversations?include_archived=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    all_ids = {row["id"] for row in all_resp.json()}
    assert set(created_ids).issubset(all_ids)


@pytest.mark.asyncio
async def test_list_search_filters_by_title_ilike(client: AsyncClient) -> None:
    token = await _register_and_login(client, "chat_search@example.com")
    for title in ["Python basics", "Rust basics", "SQL tips"]:
        await client.post(
            "/api/v1/chat/conversations",
            json={"title": title},
            headers={"Authorization": f"Bearer {token}"},
        )

    resp = await client.get(
        "/api/v1/chat/conversations?q=basics",
        headers={"Authorization": f"Bearer {token}"},
    )
    titles = {row["title"] for row in resp.json()}
    assert "Python basics" in titles
    assert "Rust basics" in titles
    assert "SQL tips" not in titles


@pytest.mark.asyncio
async def test_rename_conversation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "chat_rename@example.com")
    create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Old title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = create.json()["id"]

    patch = await client.patch(
        f"/api/v1/chat/conversations/{conv_id}",
        json={"title": "New title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["title"] == "New title"


@pytest.mark.asyncio
async def test_ownership_isolation_returns_404(client: AsyncClient) -> None:
    """A user must see 404 (not 403) when probing another user's conversation."""
    alice_token = await _register_and_login(client, "alice@example.com")
    bob_token = await _register_and_login(client, "bob@example.com")

    alice_conv = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Alice's diary"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    alice_conv_id = alice_conv.json()["id"]

    for endpoint in (
        f"/api/v1/chat/conversations/{alice_conv_id}",
        f"/api/v1/chat/conversations/{alice_conv_id}/messages",
    ):
        resp = await client.get(
            endpoint, headers={"Authorization": f"Bearer {bob_token}"}
        )
        assert resp.status_code == 404, endpoint

    # PATCH + DELETE must also 404 (not reveal existence).
    patch = await client.patch(
        f"/api/v1/chat/conversations/{alice_conv_id}",
        json={"title": "hacked"},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert patch.status_code == 404

    delete = await client.delete(
        f"/api/v1/chat/conversations/{alice_conv_id}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert delete.status_code == 404


@pytest.mark.asyncio
async def test_delete_cascades_messages(client: AsyncClient) -> None:
    """Deleting a conversation hard-deletes its messages via FK CASCADE."""
    token = await _register_and_login(client, "chat_cascade@example.com")

    # Use a real persistence path: stream a turn (LLM mocked) so we have at
    # least one user + one assistant row, then delete and confirm empty.
    fake_llm = _FakeLLM(["hi", " there"])
    with patch(
        "app.api.v1.routes.stream.build_llm", return_value=fake_llm
    ):
        stream_resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "hello tutor"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Drain the stream so the finally-block persists the assistant reply.
        async for _ in stream_resp.aiter_bytes():
            pass

    # Find the conversation we just created.
    list_resp = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    convs = list_resp.json()
    assert len(convs) >= 1
    conv_id = convs[0]["id"]
    # Both roles should have landed.
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    roles = [m["role"] for m in detail.json()["messages"]]
    assert "user" in roles and "assistant" in roles

    # Hard-delete and re-fetch.
    del_resp = await client.delete(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    gone = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert gone.status_code == 404


# ---------------------------------------------------------------------------
# Stream endpoint persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_creates_conversation_and_emits_id(client: AsyncClient) -> None:
    token = await _register_and_login(client, "stream_new@example.com")

    fake_llm = _FakeLLM(["Hello", " world"])
    with patch(
        "app.api.v1.routes.stream.build_llm", return_value=fake_llm
    ):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "why is sky blue?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    body = resp.text
    events = _parse_sse_events(body)
    assert events, f"expected at least one SSE event, got body={body!r}"
    first = events[0]
    assert first["agent_name"]
    assert "conversation_id" in first
    conv_id = first["conversation_id"]
    uuid.UUID(conv_id)

    # Persistence: the GET endpoint should show the user + assistant turns.
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    roles = [m["role"] for m in messages]
    assert roles[0] == "user"
    assert "assistant" in roles
    assert any(m["content"] == "why is sky blue?" for m in messages)
    assistant_contents = [m["content"] for m in messages if m["role"] == "assistant"]
    assert any("Hello" in c for c in assistant_contents)


@pytest.mark.asyncio
async def test_stream_appends_to_existing_conversation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "stream_append@example.com")

    create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "my thread"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = create.json()["id"]

    fake_llm = _FakeLLM(["reply-one"])
    with patch(
        "app.api.v1.routes.stream.build_llm", return_value=fake_llm
    ):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "turn 1", "conversation_id": conv_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp.aiter_bytes():
            pass

    # Second turn on the SAME conversation.
    fake_llm2 = _FakeLLM(["reply-two"])
    with patch(
        "app.api.v1.routes.stream.build_llm", return_value=fake_llm2
    ):
        resp2 = await client.post(
            "/api/v1/agents/stream",
            json={"message": "turn 2", "conversation_id": conv_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp2.aiter_bytes():
            pass

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    messages = detail.json()["messages"]
    # 2 user + 2 assistant = 4 rows
    assert len(messages) == 4
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    assert "turn 1" in user_msgs
    assert "turn 2" in user_msgs


@pytest.mark.asyncio
async def test_stream_with_foreign_conversation_id_returns_404(
    client: AsyncClient,
) -> None:
    alice_token = await _register_and_login(client, "alice_stream@example.com")
    bob_token = await _register_and_login(client, "bob_stream@example.com")

    alice_create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Alice thread"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    alice_conv = alice_create.json()["id"]

    resp = await client.post(
        "/api/v1/agents/stream",
        json={"message": "sneak", "conversation_id": alice_conv},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_messages_pagination_cursor(client: AsyncClient) -> None:
    """`/messages?limit=&before=` paginates backwards through a conversation."""
    token = await _register_and_login(client, "pagination@example.com")
    create = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "pages"},
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = create.json()["id"]

    # Seed 5 user messages via the stream endpoint (LLM mocked to return empty).
    for n in range(5):
        with patch(
            "app.api.v1.routes.stream.build_llm",
            return_value=_FakeLLM([f"a{n}"]),
        ):
            resp = await client.post(
                "/api/v1/agents/stream",
                json={"message": f"msg-{n}", "conversation_id": conv_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            async for _ in resp.aiter_bytes():
                pass

    page1 = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/messages?limit=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page1.status_code == 200
    rows = page1.json()
    assert len(rows) == 3
    # newest 3 rows returned in ascending order.
    oldest_id = rows[0]["id"]

    page2 = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/messages?limit=3&before={oldest_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page2.status_code == 200
    older_rows = page2.json()
    assert len(older_rows) >= 1
    # No overlap with page1.
    page1_ids = {r["id"] for r in rows}
    older_ids = {r["id"] for r in older_rows}
    assert page1_ids.isdisjoint(older_ids)
