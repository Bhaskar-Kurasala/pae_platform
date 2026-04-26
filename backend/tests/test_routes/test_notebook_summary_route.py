"""Route tests for /api/v1/chat/notebook/summary and the in_review filter
(Notebook + Tutor refactor 2026-04-26).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notebook_entry import NotebookEntry
from app.models.user import User


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Notebook Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


async def _user_id(db: AsyncSession, email: str) -> str:
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one()
    return str(user.id)


@pytest.mark.asyncio
async def test_summary_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/chat/notebook/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_summary_empty_user_returns_zeros(client: AsyncClient) -> None:
    token = await _register_and_login(client, "nb-summary-empty@test.dev")
    resp = await client.get(
        "/api/v1/chat/notebook/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["graduated"] == 0
    assert body["in_review"] == 0
    assert body["graduation_percentage"] == 0.0
    assert body["latest_graduated_at"] is None
    assert body["by_source"] == []
    assert body["tags"] == []


@pytest.mark.asyncio
async def test_summary_with_graduated_and_in_review_entries(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "nb-summary-mix@test.dev"
    token = await _register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}

    # Create three entries via the API (so SRS card creation runs through the
    # production code path).
    for idx, src in enumerate(["chat", "chat", "quiz"]):
        resp = await client.post(
            "/api/v1/chat/notebook",
            json={
                "message_id": f"msg-{idx}",
                "conversation_id": "conv-1",
                "content": f"Entry {idx}",
                "source_type": src,
                "tags": ["alpha"] if idx == 0 else [],
            },
            headers=auth,
        )
        assert resp.status_code == 201, resp.text

    # Graduate exactly one entry by stamping graduated_at directly on the
    # row — we don't need to drive a full SRS review here; the route is what
    # we're testing.
    user_id = await _user_id(db_session, email)
    rows = list(
        (
            await db_session.execute(
                select(NotebookEntry)
                .where(NotebookEntry.user_id == user_id)  # type: ignore[arg-type]
                .order_by(NotebookEntry.created_at.asc())
            )
        ).scalars().all()
    )
    assert len(rows) == 3
    # Pick the chat-source entry to graduate so by_source counts stay stable.
    chat_row = next(r for r in rows if r.source_type == "chat")
    grad_at = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
    chat_row.graduated_at = grad_at
    await db_session.commit()

    resp = await client.get(
        "/api/v1/chat/notebook/summary", headers=auth
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["graduated"] == 1
    assert body["in_review"] == 2
    assert body["graduation_percentage"] == round(1 / 3 * 100, 1)
    assert body["latest_graduated_at"] is not None
    by_source = {s["source"]: s["count"] for s in body["by_source"]}
    assert by_source.get("chat") == 2
    assert by_source.get("quiz") == 1
    # `tags` is the union of distinct tags across entries.
    assert "alpha" in body["tags"]


@pytest.mark.asyncio
async def test_list_in_review_filter_excludes_graduated_entries(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "nb-list-inreview@test.dev"
    token = await _register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}

    for idx in range(3):
        resp = await client.post(
            "/api/v1/chat/notebook",
            json={
                "message_id": f"m-{idx}",
                "conversation_id": "conv-1",
                "content": f"E{idx}",
            },
            headers=auth,
        )
        assert resp.status_code == 201, resp.text

    # Graduate the first one.
    user_id = await _user_id(db_session, email)
    rows = list(
        (
            await db_session.execute(
                select(NotebookEntry)
                .where(NotebookEntry.user_id == user_id)  # type: ignore[arg-type]
                .order_by(NotebookEntry.created_at.asc())
            )
        ).scalars().all()
    )
    assert len(rows) == 3
    rows[0].graduated_at = datetime.now(UTC)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/chat/notebook?graduated=in_review", headers=auth
    )
    assert resp.status_code == 200, resp.text
    listed = resp.json()
    assert len(listed) == 2
    assert all(e["graduated_at"] is None for e in listed)
