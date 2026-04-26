"""Tests for the notebook summarize service + endpoint (P-Today2).

Covers:
  * pure helpers (`_coerce_tags`, `_coerce_summary`, `_extract_json_object`,
    `_normalize_llm_content`) — no external deps required
  * `summarize_for_notebook` happy path with a mocked LLM
  * graceful fallback when the LLM raises
  * Redis cache hit short-circuits the LLM call
  * `POST /chat/notebook/summarize` route returns the right shape
  * `POST /chat/notebook` accepts `user_note` and `tags`

The Redis cache is exercised with a tiny in-memory fake — we don't need a
real Redis to verify the read/write flow.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app
from app.services import notebook_summarize_service as svc


# ---------------------------------------------------------------------------
# Pure-helper tests (no fixtures needed)
# ---------------------------------------------------------------------------


def test_coerce_tags_dedupes_and_kebabs() -> None:
    assert svc._coerce_tags("RAG, Vector Search, #Embeddings") == [
        "rag",
        "vector-search",
        "embeddings",
    ]


def test_coerce_tags_caps_at_five() -> None:
    raw = ["a", "b", "c", "d", "e", "f", "g"]
    assert svc._coerce_tags(raw) == ["a", "b", "c", "d", "e"]


def test_coerce_tags_handles_garbage() -> None:
    assert svc._coerce_tags(None) == []
    assert svc._coerce_tags(123) == []
    assert svc._coerce_tags(["", "  ", "ok"]) == ["ok"]


def test_coerce_summary_falls_back_to_head_of_text() -> None:
    out = svc._coerce_summary(None, "alpha\nbeta\ngamma\ndelta")
    # First 3 non-blank lines, formatted as bullets.
    assert out.splitlines() == ["- alpha", "- beta", "- gamma"]


def test_coerce_summary_passes_through_when_provided() -> None:
    assert svc._coerce_summary("- already a bullet", "ignored") == "- already a bullet"


def test_extract_json_object_skips_preamble() -> None:
    raw = 'thinking: I should output… {"summary": "x", "tags": ["a"]}\nend'
    parsed = svc._extract_json_object(raw)
    assert parsed == {"summary": "x", "tags": ["a"]}


def test_extract_json_object_returns_empty_on_no_json() -> None:
    assert svc._extract_json_object("no braces here") == {}


def test_normalize_llm_content_strips_thinking_blocks() -> None:
    raw = [
        {"type": "thinking", "text": "internal monologue"},
        {"type": "text", "text": "real output"},
    ]
    assert svc._normalize_llm_content(raw) == "real output"


def test_normalize_llm_content_passes_string() -> None:
    assert svc._normalize_llm_content("plain") == "plain"


# ---------------------------------------------------------------------------
# Summarize service: LLM happy path, fallback path, cache path
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal async redis-compatible store used to verify cache flow."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets = 0
        self.sets = 0

    async def get(self, key: str) -> str | None:
        self.gets += 1
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.sets += 1
        self.store[key] = value


def _make_fake_llm(content: Any) -> Any:
    """Build a fake `build_llm()` return value whose `ainvoke` returns *content*."""
    fake_llm = MagicMock()
    fake_response = MagicMock()
    fake_response.content = content
    fake_llm.ainvoke = AsyncMock(return_value=fake_response)
    return fake_llm


@pytest.mark.asyncio
async def test_summarize_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(svc, "get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(
        svc,
        "build_llm",
        lambda **kwargs: _make_fake_llm(
            json.dumps(
                {
                    "summary": "- generators are lazy iterators\n- they pause and resume",
                    "tags": ["python", "generators", "iterators"],
                }
            )
        ),
    )

    result = await svc.summarize_for_notebook(
        message_id="m-1",
        content="Generators are lazy iterators in Python that pause and resume "
        "their execution, holding their state between yields.",
        user_question="What are generators?",
    )

    assert "generators are lazy" in result.summary
    assert result.tags == ["python", "generators", "iterators"]
    assert result.cached is False
    # The result should now be cached for next time.
    assert fake_redis.sets == 1


@pytest.mark.asyncio
async def test_summarize_returns_cached_on_second_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(svc, "get_redis", AsyncMock(return_value=fake_redis))
    fake_llm_factory = MagicMock(
        return_value=_make_fake_llm(
            json.dumps({"summary": "- one", "tags": ["x"]})
        )
    )
    monkeypatch.setattr(svc, "build_llm", fake_llm_factory)

    args = dict(message_id="m-cache", content="Some long answer text here.")
    first = await svc.summarize_for_notebook(**args)
    second = await svc.summarize_for_notebook(**args)

    assert first.cached is False
    assert second.cached is True
    # LLM only called once — second call hit the cache.
    assert fake_llm_factory.call_count == 1


@pytest.mark.asyncio
async def test_summarize_falls_back_when_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(svc, "get_redis", AsyncMock(return_value=fake_redis))

    def _raise(**_: Any) -> Any:
        raise RuntimeError("LLM API down")

    monkeypatch.setattr(svc, "build_llm", _raise)

    result = await svc.summarize_for_notebook(
        message_id="m-down",
        content="line one\nline two\nline three",
    )

    # Falls back to head-of-text bullets — never raises, never empty.
    assert result.summary != ""
    assert "line one" in result.summary
    assert result.tags == []
    assert result.cached is False


@pytest.mark.asyncio
async def test_summarize_skips_empty_content(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = MagicMock()
    monkeypatch.setattr(svc, "build_llm", lambda **_: fake_llm)
    result = await svc.summarize_for_notebook(message_id="m", content="   ")
    assert result.summary == ""
    assert result.tags == []
    fake_llm.ainvoke.assert_not_called()


# ---------------------------------------------------------------------------
# HTTP endpoint tests (POST /chat/notebook/summarize, POST /chat/notebook)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    # Mock the LLM + Redis at the service level so the endpoint runs end-to-end
    # without external deps.
    fake_redis = _FakeRedis()
    monkeypatch.setattr(svc, "get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(
        svc,
        "build_llm",
        lambda **_: _make_fake_llm(
            json.dumps(
                {
                    "summary": "- key idea bullet\n- supporting detail",
                    "tags": ["topic-a", "topic-b"],
                }
            )
        ),
    )

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
async def test_summarize_endpoint_returns_summary(client: AsyncClient) -> None:
    token = await _register_and_login(client, "summ-1@test.com")
    resp = await client.post(
        "/api/v1/chat/notebook/summarize",
        json={
            "message_id": "msg-1",
            "content": "A long assistant reply about retrieval-augmented generation.",
            "user_question": "What is RAG?",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["summary"].startswith("- key idea")
    assert data["suggested_tags"] == ["topic-a", "topic-b"]
    assert data["cached"] is False


@pytest.mark.asyncio
async def test_summarize_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/chat/notebook/summarize",
        json={"message_id": "m", "content": "x"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_save_to_notebook_persists_user_note_and_tags(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "save-1@test.com")
    auth = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/chat/notebook",
        json={
            "message_id": "msg-9",
            "conversation_id": "conv-9",
            "content": "Raw assistant reply preserved as audit trail.",
            "title": "RAG basics",
            "user_note": "- RAG retrieves docs and injects them as context\n- Solves stale-knowledge problem",
            "tags": ["rag", "embeddings"],
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["user_note"].startswith("- RAG retrieves docs")
    assert data["tags"] == ["rag", "embeddings"]
    assert data["content"] == "Raw assistant reply preserved as audit trail."

    # And the list endpoint round-trips both fields.
    list_resp = await client.get("/api/v1/chat/notebook", headers=auth)
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert len(rows) == 1
    assert rows[0]["user_note"].startswith("- RAG retrieves docs")
    assert rows[0]["tags"] == ["rag", "embeddings"]
