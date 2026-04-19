"""Tests for the P1-2 regenerate-assistant-message surface.

Covers:
  - auth required
  - regenerating an assistant reply creates a NEW sibling row with the
    same `parent_id` (the user turn) without deleting the original
  - ownership 404 (cross-user probing)
  - regenerating a missing id returns 404
  - regenerating a user-role message returns 400
  - the conversation GET response collapses to the canonical (latest)
    sibling per parent and inlines `sibling_ids` on messages whose parent
    has >1 child
  - a non-last assistant message can still be regenerated
  - the single-message GET endpoint returns the requested variant with
    the correct sibling set inlined
  - SSE stream includes the `regenerated_from` field on the first event
    and the `X-Regenerated-From` header
"""

from __future__ import annotations

import json
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


async def _seed_conversation(
    client: AsyncClient,
    token: str,
    *,
    message: str = "explain recursion",
    tokens: list[str] | None = None,
    conversation_id: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Stream one turn and return (conversation_id, message_rows)."""
    fake_llm = _FakeLLM(tokens or ["original", " reply"])
    payload: dict[str, Any] = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp.aiter_bytes():
            pass

    if conversation_id is None:
        list_resp = await client.get(
            "/api/v1/chat/conversations",
            headers={"Authorization": f"Bearer {token}"},
        )
        conv_id = list_resp.json()[0]["id"]
    else:
        conv_id = conversation_id

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return conv_id, list(detail.json()["messages"])


async def _regenerate(
    client: AsyncClient,
    token: str,
    assistant_id: str,
    *,
    tokens: list[str],
) -> tuple[int, bytes, dict[str, str]]:
    """POST regenerate and drain the SSE body. Returns (status, body, headers)."""
    fake_llm = _FakeLLM(tokens)
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            f"/api/v1/chat/messages/{assistant_id}/regenerate",
            headers={"Authorization": f"Bearer {token}"},
        )
        chunks: list[bytes] = []
        async for chunk in resp.aiter_bytes():
            chunks.append(chunk)
    return resp.status_code, b"".join(chunks), dict(resp.headers)


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regenerate_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/chat/messages/{uuid.uuid4()}/regenerate",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_regenerate_creates_sibling_keeps_original(
    client: AsyncClient,
) -> None:
    """Happy path: regenerate produces a NEW assistant row with the same
    parent_id as the original; the original stays visible (not deleted)."""
    token = await _register_and_login(client, "regen_happy@example.com")
    _, messages = await _seed_conversation(client, token, tokens=["first", " variant"])
    assert len(messages) == 2
    user_row = next(m for m in messages if m["role"] == "user")
    original_assistant = next(m for m in messages if m["role"] == "assistant")
    assert original_assistant["parent_id"] == user_row["id"]

    status_code, body, headers = await _regenerate(
        client, token, original_assistant["id"], tokens=["second", " variant"]
    )
    assert status_code == 200
    assert headers.get("x-regenerated-from") == original_assistant["id"]
    # First SSE event should carry `regenerated_from`.
    text = body.decode("utf-8")
    first_line = text.split("\n\n", 1)[0]
    assert first_line.startswith("data: ")
    first_payload = json.loads(first_line[len("data: "):])
    assert first_payload["regenerated_from"] == original_assistant["id"]

    # Fetch conversation: canonical view hides the older sibling, but both
    # share the same parent_id and live in the DB.
    conv_id = user_row["conversation_id"]
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    msgs = detail.json()["messages"]
    # Canonical chain: user + most-recent assistant only.
    assert len(msgs) == 2
    canonical_assistant = msgs[1]
    assert canonical_assistant["role"] == "assistant"
    assert canonical_assistant["parent_id"] == user_row["id"]
    # Sibling ids inlined — both variants present.
    assert len(canonical_assistant["sibling_ids"]) == 2
    assert original_assistant["id"] in canonical_assistant["sibling_ids"]
    assert canonical_assistant["id"] in canonical_assistant["sibling_ids"]
    # The canonical choice is the NEW (latest) variant, not the original.
    assert canonical_assistant["id"] != original_assistant["id"]
    assert canonical_assistant["content"] == "second variant"


@pytest.mark.asyncio
async def test_regenerate_ownership_returns_404(client: AsyncClient) -> None:
    """Bob cannot regenerate Alice's message — 404 (not 403) to avoid ID leaks."""
    alice = await _register_and_login(client, "regen_alice@example.com")
    bob = await _register_and_login(client, "regen_bob@example.com")
    _, messages = await _seed_conversation(client, alice)
    alice_assistant_id = next(
        m for m in messages if m["role"] == "assistant"
    )["id"]

    status_code, _, _ = await _regenerate(
        client, bob, alice_assistant_id, tokens=["nope"]
    )
    assert status_code == 404


@pytest.mark.asyncio
async def test_regenerate_nonexistent_message_returns_404(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "regen_ghost@example.com")
    status_code, _, _ = await _regenerate(
        client, token, str(uuid.uuid4()), tokens=["nope"]
    )
    assert status_code == 404


@pytest.mark.asyncio
async def test_regenerate_user_message_returns_400(client: AsyncClient) -> None:
    """Regenerating a user turn is nonsensical — endpoint rejects it."""
    token = await _register_and_login(client, "regen_user@example.com")
    _, messages = await _seed_conversation(client, token)
    user_id = next(m for m in messages if m["role"] == "user")["id"]

    status_code, _, _ = await _regenerate(
        client, token, user_id, tokens=["nope"]
    )
    assert status_code == 400


@pytest.mark.asyncio
async def test_regenerate_single_message_response_inlines_siblings(
    client: AsyncClient,
) -> None:
    """GET /messages/{id} should return the requested variant with the
    sibling set inlined so the <1/N> navigator can key by id."""
    token = await _register_and_login(client, "regen_single@example.com")
    _, messages = await _seed_conversation(client, token, tokens=["v1"])
    original_id = next(m for m in messages if m["role"] == "assistant")["id"]

    status_code, _, _ = await _regenerate(
        client, token, original_id, tokens=["v2"]
    )
    assert status_code == 200

    # Fetch the ORIGINAL (now an older sibling) by id; it should still
    # expose the sibling_ids list including both variants.
    resp = await client.get(
        f"/api/v1/chat/messages/{original_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "assistant"
    assert body["content"] == "v1"
    assert len(body["sibling_ids"]) == 2
    assert original_id in body["sibling_ids"]


@pytest.mark.asyncio
async def test_regenerate_non_last_assistant(client: AsyncClient) -> None:
    """Regenerate works on a mid-conversation assistant, not just the tail."""
    token = await _register_and_login(client, "regen_middle@example.com")
    conv_id, first_msgs = await _seed_conversation(
        client, token, message="turn one", tokens=["reply", " one"]
    )
    # Append a second turn.
    _, _ = await _seed_conversation(
        client,
        token,
        message="turn two",
        tokens=["reply", " two"],
        conversation_id=conv_id,
    )

    # Re-fetch to get the full ordering.
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    msgs = detail.json()["messages"]
    assert len(msgs) == 4  # [u1, a1, u2, a2]
    first_assistant_id = msgs[1]["id"]
    first_user_id = msgs[0]["id"]
    assert msgs[1]["parent_id"] == first_user_id

    # Regenerate the FIRST assistant (not the latest).
    status_code, _, _ = await _regenerate(
        client, token, first_assistant_id, tokens=["reply", " one-prime"]
    )
    assert status_code == 200

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    msgs = detail.json()["messages"]
    # Canonical chain: u1, a1' (new), u2, a2 — still 4 rows, older a1 hidden.
    assert len(msgs) == 4
    assert msgs[0]["id"] == first_user_id
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["parent_id"] == first_user_id
    assert msgs[1]["id"] != first_assistant_id  # newer sibling surfaced
    assert len(msgs[1]["sibling_ids"]) == 2
    # Second turn's sibling_ids stays empty (only one variant).
    assert msgs[3]["sibling_ids"] == []


@pytest.mark.asyncio
async def test_sibling_ids_empty_when_single_variant(
    client: AsyncClient,
) -> None:
    """Messages whose parent has only one child should NOT get a
    sibling_ids list (keeps wire payload small, and the UI hides the
    navigator when the list is empty)."""
    token = await _register_and_login(client, "regen_single_variant@example.com")
    conv_id, messages = await _seed_conversation(client, token)
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assistant = next(
        m for m in detail.json()["messages"] if m["role"] == "assistant"
    )
    assert assistant["sibling_ids"] == []
