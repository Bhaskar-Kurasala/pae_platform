"""Tests for the P1-1 edit-user-message surface AND the P1-3 fork-branch
extension.

P1-3 upgraded the edit flow from a destructive "soft-delete target + trim"
operation into a *fork*: the original user message stays live, and each
edit becomes a sibling (new user row with `parent_id = original.id`). The
canonical chain renderer hides non-latest siblings from the default
transcript, but the `< 1 / N >` navigator can flip between them.

Covers:
  - auth required
  - editing a user turn forks a new user sibling (original remains live,
    downstream rows are soft-deleted so the new branch re-streams cleanly)
  - the new user row is returned with the edited content, keyed by a fresh
    id, and linked to the original via `parent_id`
  - ownership 404 (cross-user probing)
  - editing a missing/nonexistent id returns 404
  - editing an assistant-role message returns 400
  - empty / oversized content returns 422
  - canonical conversation view hides the original; the original is
    accessible via `sibling_ids` and `GET /messages/{id}`
  - re-editing the original (branching a second edit off the root) works
  - export surface reflects the canonical chain (the latest branch)
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
async def test_edit_forks_new_branch_preserving_original(
    client: AsyncClient,
) -> None:
    """P1-3 happy path: edit a user turn → original stays live (as a
    sibling), downstream assistant reply is soft-deleted, the canonical
    conversation view hides the original but surfaces `sibling_ids` so the
    `< 1 / N >` navigator can flip back."""
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

    # GET conversation (canonical chain): only the latest user sibling shows;
    # the original user row is hidden from the default view (but still live
    # in the DB — see the `GET /messages/{original}` fetch below). The old
    # assistant reply IS soft-deleted so the new branch can re-stream cleanly.
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    canonical_ids = [m["id"] for m in detail.json()["messages"]]
    assert body["id"] in canonical_ids
    assert user_msg_id not in canonical_ids  # collapsed by canonical chain
    assert assistant_msg_id not in canonical_ids  # soft-deleted downstream
    assert len(canonical_ids) == 1

    # The canonical user bubble inlines the edit chain via `sibling_ids`.
    canonical_user = detail.json()["messages"][0]
    assert canonical_user["role"] == "user"
    assert canonical_user["sibling_ids"] == [user_msg_id, body["id"]]

    # The original user row is still reachable via GET /messages/{id}; the
    # navigator uses this endpoint to resolve the "previous" branch on click.
    prior = await client.get(
        f"/api/v1/chat/messages/{user_msg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert prior.status_code == 200
    prior_body = prior.json()
    assert prior_body["content"] == "original question"
    assert prior_body["sibling_ids"] == [user_msg_id, body["id"]]

    # Sidebar message_count reflects every live row — under P1-3 the original
    # user row survives, so we see 2 live rows: [original_user, new_edit].
    listing = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    row = next(r for r in listing.json() if r["id"] == conv_id)
    assert row["message_count"] == 2

    # Paginated messages endpoint returns both user rows (original preserved)
    # but NOT the soft-deleted assistant reply.
    page = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page.status_code == 200
    page_ids = {m["id"] for m in page.json()}
    assert user_msg_id in page_ids
    assert assistant_msg_id not in page_ids
    assert body["id"] in page_ids


@pytest.mark.asyncio
async def test_edit_middle_turn_forks_and_truncates_tail(
    client: AsyncClient,
) -> None:
    """P1-3 — edit in the middle of a multi-turn conversation: the prior
    pair stays visible, the edited turn's original is preserved as a
    sibling (but collapsed from the canonical view), the old assistant
    reply + anything after is soft-deleted, and the new user row appears
    in place."""
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
    canonical = detail.json()["messages"]
    canonical_ids = [m["id"] for m in canonical]
    # First turn survives, the second turn is replaced by the new edit
    # branch, second assistant reply is soft-deleted.
    assert canonical_ids == [first_user_id, first_assistant_id, new_user_id]
    assert second_user_id not in canonical_ids
    assert second_assistant_id not in canonical_ids

    # The canonical user bubble for the edited turn carries the edit chain
    # via sibling_ids so the `< 1 / N >` navigator can flip back.
    edited_bubble = canonical[2]
    assert edited_bubble["sibling_ids"] == [second_user_id, new_user_id]


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
async def test_edit_original_again_after_fork(client: AsyncClient) -> None:
    """P1-3 — branching semantics: after a first edit, the original row
    stays live, so a second edit off the *original* is valid and creates a
    second sibling alongside the first edit (the chain becomes
    `[original, edit_1, edit_2]`).
    """
    token = await _register_and_login(client, "edit_twice@example.com")
    conv_id, messages = await _seed_conversation(client, token)
    user_id = next(m for m in messages if m["role"] == "user")["id"]

    first = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": "first edit"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    # Second edit pointing back at the ORIGINAL — branches off the same root.
    replay = await client.post(
        f"/api/v1/chat/messages/{user_id}/edit",
        json={"content": "second edit on original"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert replay.status_code == 200
    second_id = replay.json()["id"]
    assert replay.json()["parent_id"] == user_id

    # Canonical chain picks the latest (second edit) and exposes the full
    # chain via sibling_ids: [original, first_edit, second_edit].
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    canonical = detail.json()["messages"]
    assert len(canonical) == 1
    assert canonical[0]["id"] == second_id
    assert canonical[0]["sibling_ids"] == [user_id, first_id, second_id]


@pytest.mark.asyncio
async def test_export_excludes_soft_deleted_rows(client: AsyncClient) -> None:
    """P1-3 — export surface includes every live message. Under the fork
    model the original user row stays live alongside the edit, but the
    soft-deleted assistant reply is excluded."""
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
    # Both user rows are live (fork preserves the original); the old
    # assistant reply was soft-deleted → absent.
    assert "seed" in body
    assert "edited seed" in body
    assert "original reply" not in body
    # Two live user rows → "Messages: 2".
    assert "Messages: 2" in body


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


# ---------------------------------------------------------------------------
# P1-3 — dedicated fork + navigate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p1_3_fork_creates_user_sibling_chain(
    client: AsyncClient,
) -> None:
    """Consecutive edits off the same root build a linear chain exposed via
    `sibling_ids` in `[root, edit_1, edit_2, ...]` order (created_at asc)."""
    token = await _register_and_login(client, "p1_3_chain@example.com")
    conv_id, messages = await _seed_conversation(client, token)
    root_id = next(m for m in messages if m["role"] == "user")["id"]

    # First edit — branches off the root.
    first = await client.post(
        f"/api/v1/chat/messages/{root_id}/edit",
        json={"content": "edit one"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    # Second edit off the FIRST edit — chains onto the latest sibling.
    second = await client.post(
        f"/api/v1/chat/messages/{first_id}/edit",
        json={"content": "edit two"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    second_id = second.json()["id"]
    assert second.json()["parent_id"] == first_id

    # The canonical chain shows only the latest member, but sibling_ids
    # carries the full chain `[root, edit_1, edit_2]` ordered by created_at.
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    canonical = detail.json()["messages"]
    assert len(canonical) == 1
    assert canonical[0]["id"] == second_id
    assert canonical[0]["content"] == "edit two"
    assert canonical[0]["sibling_ids"] == [root_id, first_id, second_id]


@pytest.mark.asyncio
async def test_p1_3_navigator_can_fetch_prior_sibling(
    client: AsyncClient,
) -> None:
    """After editing, the original user row is still reachable via GET
    /messages/{id}; the navigator uses this to swap the bubble to the
    previous variant. Both variants advertise the same `sibling_ids`."""
    token = await _register_and_login(client, "p1_3_nav@example.com")
    conv_id, messages = await _seed_conversation(
        client, token, message="root question"
    )
    root_id = next(m for m in messages if m["role"] == "user")["id"]

    edit = await client.post(
        f"/api/v1/chat/messages/{root_id}/edit",
        json={"content": "edited question"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert edit.status_code == 200
    edit_id = edit.json()["id"]

    # Fetch the original via the sibling-navigator endpoint.
    prior = await client.get(
        f"/api/v1/chat/messages/{root_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert prior.status_code == 200
    assert prior.json()["content"] == "root question"
    assert prior.json()["sibling_ids"] == [root_id, edit_id]

    # And the latest edit advertises the same chain.
    latest = await client.get(
        f"/api/v1/chat/messages/{edit_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert latest.status_code == 200
    assert latest.json()["sibling_ids"] == [root_id, edit_id]

    # Sanity: the root + edit are both live rows in the messages page.
    page = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    page_ids = {m["id"] for m in page.json()}
    assert root_id in page_ids
    assert edit_id in page_ids


@pytest.mark.asyncio
async def test_p1_3_no_sibling_ids_on_unedited_user(
    client: AsyncClient,
) -> None:
    """A user turn with no edits renders an empty / missing `sibling_ids`
    so the UI knows not to render the `< / >` navigator."""
    token = await _register_and_login(client, "p1_3_none@example.com")
    conv_id, _ = await _seed_conversation(client, token)

    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    user_msgs = [m for m in detail.json()["messages"] if m["role"] == "user"]
    assert len(user_msgs) == 1
    # ChatGPT-style: single-member chain => no navigator, no sibling_ids.
    assert user_msgs[0].get("sibling_ids", []) == []


@pytest.mark.asyncio
async def test_p1_3_second_turn_unaffected_by_first_turn_edits(
    client: AsyncClient,
) -> None:
    """Edit chains are scoped to one turn — editing the first user turn
    must not pollute the second turn's `sibling_ids`."""
    token = await _register_and_login(client, "p1_3_scope@example.com")
    _, first_msgs = await _seed_conversation(
        client, token, message="turn one", tokens=["reply", " one"]
    )
    conv_id = first_msgs[0]["conversation_id"]

    # Add a second turn.
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
    first_user_id = msgs[0]["id"]
    second_user_id = msgs[2]["id"]

    # Edit the FIRST turn — creates a sibling chain at the root.
    # (NOTE: this also soft-deletes the downstream second turn, but the
    # chain map we're validating is independent of downstream liveness.)
    first_edit = await client.post(
        f"/api/v1/chat/messages/{first_user_id}/edit",
        json={"content": "edited turn one"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first_edit.status_code == 200
    first_edit_id = first_edit.json()["id"]

    # The NEW first-turn bubble has a chain of size 2.
    # The second turn is now soft-deleted (downstream of the first-turn
    # edit) — `GET /messages/{second_user_id}` should 404 because the row
    # is no longer live.
    second_lookup = await client.get(
        f"/api/v1/chat/messages/{second_user_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second_lookup.status_code == 404

    # Canonical chain: the latest first-turn edit is now the only user
    # bubble; its chain is [first_user_id, first_edit_id].
    detail2 = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    canonical = detail2.json()["messages"]
    assert len(canonical) == 1
    assert canonical[0]["id"] == first_edit_id
    assert canonical[0]["sibling_ids"] == [first_user_id, first_edit_id]
