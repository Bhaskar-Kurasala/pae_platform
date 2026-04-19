"""Tests for the P1-1 edit-user-message surface.

Covers:
  - auth required
  - editing a user turn soft-deletes the target + every downstream row
    (preserving the audit trail in the DB but hiding from default queries)
  - a brand-new user row is returned with the edited content, keyed by a
    fresh id, and linked to the original via `parent_id`
  - ownership 404 (cross-user probing)
  - editing a missing/nonexistent id returns 404
  - editing an assistant-role message returns 400
  - empty / oversized content returns 422
  - list/get conversation surfaces exclude the soft-deleted rows
  - export surface excludes the soft-deleted rows
  - admin feedback rollup excludes feedback on soft-deleted messages by
    default (belt-and-braces — `include_deleted` param stays False there)
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


async def _seed_conversation(
    client: AsyncClient,
    token: str,
    *,
    message: str = "original question",
    tokens: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Stream one turn and return (conversation_id, message_rows)."""
    fake_llm = _FakeLLM(tokens or ["Hello", " there"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": message},
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
    return conv_id, list(detail.json()["messages"])


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/chat/messages/{uuid.uuid4()}/edit",
        json={"content": "updated"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_edit_soft_deletes_and_creates_new_message(
    client: AsyncClient,
) -> None:
    """Happy path: edit a user turn → downstream rows soft-deleted, new user
    message returned, list/get exclude the deleted rows."""
    token = await _register_and_login(client, "edit_happy@example.com")
    conv_id, messages = await _seed_conversation(client, token)

    # Seed produces [user, assistant]. Grab both.
    assert len(messages) == 2
    user_row = next(m for m in messages if m["role"] == "user")
    assistant_row = next(m for m in messages if m["role"] == "assistant")
    user_msg_id = user_row["id"]
    assistant_msg_id = assistant_row["id"]

    resp = await client.post(
        f"/api/v1/chat/messages/{user_msg_id}/edit",
        json={"content": "rewritten question"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "user"
    assert body["content"] == "rewritten question"
    assert body["parent_id"] == user_msg_id
    assert body["id"] != user_msg_id
    assert body["conversation_id"] == conv_id

    # GET conversation: only the new user row should be visible. The original
    # user + assistant turn are soft-deleted.
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    visible_ids = {m["id"] for m in detail.json()["messages"]}
    assert body["id"] in visible_ids
    assert user_msg_id not in visible_ids
    assert assistant_msg_id not in visible_ids
    assert len(visible_ids) == 1

    # Sidebar list must reflect the same message_count (1, not 3).
    listing = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    row = next(r for r in listing.json() if r["id"] == conv_id)
    assert row["message_count"] == 1

    # Paginated messages endpoint also excludes deleted.
    page = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page.status_code == 200
    page_ids = {m["id"] for m in page.json()}
    assert user_msg_id not in page_ids
    assert assistant_msg_id not in page_ids
    assert body["id"] in page_ids


@pytest.mark.asyncio
async def test_edit_middle_turn_truncates_tail(client: AsyncClient) -> None:
    """Edit in the middle of a multi-turn conversation: everything from the
    edit point onward should be soft-deleted."""
    token = await _register_and_login(client, "edit_middle@example.com")
    _, first_msgs = await _seed_conversation(
        client, token, message="turn one", tokens=["reply", " one"]
    )
    conv_id = next(
        m for m in first_msgs if m["role"] == "assistant"
    )["conversation_id"]

    # Append a second turn to the same conversation.
    fake_llm = _FakeLLM(["reply", " two"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "turn two", "conversation_id": conv_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp.aiter_bytes():
            pass

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    msgs = detail.json()["messages"]
    assert len(msgs) == 4  # [u1, a1, u2, a2]
    first_user_id = msgs[0]["id"]
    first_assistant_id = msgs[1]["id"]
    second_user_id = msgs[2]["id"]
    second_assistant_id = msgs[3]["id"]

    # Edit the SECOND user turn; the earlier pair must stay visible.
    resp = await client.post(
        f"/api/v1/chat/messages/{second_user_id}/edit",
        json={"content": "rewritten second turn"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    new_user_id = resp.json()["id"]

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    visible_ids = [m["id"] for m in detail.json()["messages"]]
    # First turn survives, second + its reply are gone, new user row appended.
    assert first_user_id in visible_ids
    assert first_assistant_id in visible_ids
    assert second_user_id not in visible_ids
    assert second_assistant_id not in visible_ids
    assert new_user_id in visible_ids
    assert len(visible_ids) == 3


@pytest.mark.asyncio
async def test_edit_ownership_returns_404(client: AsyncClient) -> None:
    """Bob cannot edit Alice's user message — 404 (not 403) to avoid ID leaks."""
    alice = await _register_and_login(client, "edit_alice@example.com")
    bob = await _register_and_login(client, "edit_bob@example.com")
    _, messages = await _seed_conversation(client, alice)
    alice_user_id = next(m for m in messages if m["role"] == "user")["id"]

    resp = await client.post(
        f"/api/v1/chat/messages/{alice_user_id}/edit",
        json={"content": "nope"},
        headers={"Authorization": f"Bearer {bob}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_edit_nonexistent_message_returns_404(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "edit_ghost@example.com")
    resp = await client.post(
        f"/api/v1/chat/messages/{uuid.uuid4()}/edit",
        json={"content": "haunt the void"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_edit_assistant_message_returns_400(client: AsyncClient) -> None:
    """Editing an assistant reply is the regenerate flow — this endpoint rejects it."""
    token = await _register_and_login(client, "edit_assistant@example.com")
    _, messages = await _seed_conversation(client, token)
    assistant_id = next(m for m in messages if m["role"] == "assistant")["id"]

    resp = await client.post(
        f"/api/v1/chat/messages/{assistant_id}/edit",
        json={"content": "try me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_edit_empty_content_returns_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "edit_empty@example.com")
    _, messages = await _seed_conversation(client, token)
    user_id = next(m for m in messages if m["role"] == "user")["id"]

    empty = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_edit_oversized_content_returns_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "edit_huge@example.com")
    _, messages = await _seed_conversation(client, token)
    user_id = next(m for m in messages if m["role"] == "user")["id"]

    too_big = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": "x" * 10_001},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert too_big.status_code == 422


@pytest.mark.asyncio
async def test_edit_missing_content_field_returns_422(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "edit_missing@example.com")
    _, messages = await _seed_conversation(client, token)
    user_id = next(m for m in messages if m["role"] == "user")["id"]

    resp = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_edit_re_edit_soft_deleted_row_404(client: AsyncClient) -> None:
    """After an edit, the original row is soft-deleted → treating it as
    missing (404), not accessible for a second edit round-trip."""
    token = await _register_and_login(client, "edit_twice@example.com")
    _, messages = await _seed_conversation(client, token)
    user_id = next(m for m in messages if m["role"] == "user")["id"]

    first = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": "first edit"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200

    # Original row is now soft-deleted → 404.
    replay = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": "second edit on original"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert replay.status_code == 404


@pytest.mark.asyncio
async def test_export_excludes_soft_deleted_rows(client: AsyncClient) -> None:
    """Markdown export surface should only include live messages after an edit."""
    token = await _register_and_login(client, "edit_export@example.com")
    conv_id, messages = await _seed_conversation(
        client, token, message="seed", tokens=["original", " reply"]
    )
    user_id = next(m for m in messages if m["role"] == "user")["id"]

    edit = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": "edited seed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert edit.status_code == 200

    export = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/export?format=md",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert export.status_code == 200
    body = export.text
    # Original content + assistant reply were soft-deleted → must be absent.
    assert "seed" in body  # the edited text contains "seed" so this is loose
    assert "edited seed" in body
    # The original user text was literally "seed" (exact); the new content is
    # "edited seed" — verify the assistant reply ("original reply") isn't there.
    assert "original reply" not in body
    # Header message count reflects only the single live user row.
    assert "Messages: 1" in body


@pytest.mark.asyncio
async def test_admin_rollup_skips_deleted_feedback(
    client: AsyncClient,
) -> None:
    """Feedback on a soft-deleted message is filtered out of the admin rollup."""
    admin_token = await _register_and_login(
        client, "edit_admin@example.com", role="admin"
    )
    student_token = await _register_and_login(
        client, "edit_student@example.com"
    )

    _, messages = await _seed_conversation(client, student_token)
    user_id = next(m for m in messages if m["role"] == "user")["id"]
    assistant_id = next(m for m in messages if m["role"] == "assistant")["id"]

    # Student thumbs-down the assistant reply.
    await client.post(
        f"/api/v1/chat/messages/{assistant_id}/feedback",
        json={"rating": "down", "reasons": ["incorrect"], "comment": "bad"},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    # Baseline: rollup sees the down vote.
    before = await client.get(
        "/api/v1/admin/chat-feedback?since_days=30",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert before.status_code == 200
    assert before.json()["down_count"] == 1

    # Edit the user turn → assistant message gets soft-deleted.
    edit = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": "rewritten"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert edit.status_code == 200

    # Rollup now excludes the feedback tied to the deleted message.
    after = await client.get(
        "/api/v1/admin/chat-feedback?since_days=30",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert after.status_code == 200
    data = after.json()
    assert data["down_count"] == 0
    assert data["up_count"] == 0
    assert data["top_reasons"] == []
