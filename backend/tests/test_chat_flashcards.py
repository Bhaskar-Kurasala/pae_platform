"""P-Today3 (2026-04-26) — backend tests for POST /api/v1/chat/flashcards.

The route used to call the spaced_repetition agent to extract Q/A pairs from
an assistant message. That path was removed because (a) the LLM frequently
returned non-parseable text, triggering a junk fallback card, and (b)
auto-extraction defeats the generation effect — writing the card in your
own words is what makes spaced repetition actually work.

Cards are now student-authored. These tests cover:
  * successful create with multiple cards
  * code-fence stripping from `back` + cards_trimmed counter
  * dedupe by normalized front
  * length validation (front >140, back >280)
  * cap of 10 cards per call
  * empty/whitespace-only cards rejected by Pydantic
  * auth required
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
            "password": "Passw0rd!",
            "full_name": "Flash Test",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Passw0rd!"},
    )
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


@pytest.mark.asyncio
async def test_create_flashcards_persists_user_authored_cards(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "fc-1@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "msg-1",
            "conversation_id": "conv-1",
            "cards": [
                {
                    "front": "What is RAG?",
                    "back": "Retrieval-Augmented Generation — query a knowledge base, inject the docs into the prompt.",
                },
                {
                    "front": "Why use RAG over fine-tuning?",
                    "back": "Cheaper to update; grounds answers in current docs.",
                },
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["cards_added"] == 2
    assert body["cards_trimmed"] == 0
    assert [c["question"] for c in body["cards"]] == [
        "What is RAG?",
        "Why use RAG over fine-tuning?",
    ]


@pytest.mark.asyncio
async def test_code_fences_stripped_from_back_and_counted(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "fc-2@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "msg-2",
            "conversation_id": "conv-2",
            "cards": [
                {
                    "front": "What does yield do?",
                    "back": "Pauses the function.\n```python\ndef gen():\n    yield 1\n```\nResumes on next().",
                },
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["cards_added"] == 1
    assert body["cards_trimmed"] == 1
    # Code fence gone, whitespace collapsed to single spaces.
    assert "```" not in body["cards"][0]["answer"]
    assert "Pauses the function." in body["cards"][0]["answer"]
    assert "Resumes on next()." in body["cards"][0]["answer"]


@pytest.mark.asyncio
async def test_duplicate_fronts_deduped_within_request(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "fc-3@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "msg-3",
            "conversation_id": "conv-3",
            "cards": [
                {"front": "What is yield?", "back": "Pauses execution."},
                {"front": "What is YIELD?", "back": "A keyword in Python."},
                {"front": "Different cue", "back": "Different answer."},
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Second card collides on front (case-insensitive) and is dropped.
    assert body["cards_added"] == 2
    fronts = [c["question"] for c in body["cards"]]
    assert fronts == ["What is yield?", "Different cue"]


@pytest.mark.asyncio
async def test_front_too_long_rejected_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fc-4@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "m",
            "conversation_id": "c",
            "cards": [
                {"front": "x" * 141, "back": "ok"},
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_back_too_long_rejected_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fc-5@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "m",
            "conversation_id": "c",
            "cards": [
                {"front": "front", "back": "x" * 281},
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_more_than_10_cards_rejected_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fc-6@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "m",
            "conversation_id": "c",
            "cards": [
                {"front": f"q{i}", "back": f"a{i}"} for i in range(11)
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_cards_array_rejected_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fc-7@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={"message_id": "m", "conversation_id": "c", "cards": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pure_codefence_back_drops_card(client: AsyncClient) -> None:
    """A back containing only a code fence becomes empty after stripping —
    we drop it rather than persist a junk row."""
    token = await _register_and_login(client, "fc-8@test.com")
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "m",
            "conversation_id": "c",
            "cards": [
                {"front": "code thing", "back": "```python\nprint(1)\n```"},
                {"front": "real card", "back": "real answer"},
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["cards_added"] == 1
    assert body["cards"][0]["question"] == "real card"


@pytest.mark.asyncio
async def test_create_flashcards_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/chat/flashcards",
        json={
            "message_id": "m",
            "conversation_id": "c",
            "cards": [{"front": "q", "back": "a"}],
        },
    )
    assert resp.status_code == 401
