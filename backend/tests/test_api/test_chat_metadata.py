"""P2-5 — message metadata persistence on stream completion.

Verifies that when the assistant turn finishes streaming, the five hover-
panel metadata columns get stamped on the `chat_messages` row:

  - `first_token_ms`    : >0 wall-clock ms to the first non-empty token
  - `total_duration_ms` : >= first_token_ms; stamped in the finally:
  - `input_tokens`      : pulled from langchain chunk `usage_metadata`
  - `output_tokens`     : pulled from langchain chunk `usage_metadata`
  - `model`             : pulled from chunk `response_metadata.model`, with
                          fallback to the configured default

The test uses a `_FakeLLM` whose chunks carry `usage_metadata` and
`response_metadata`, mirroring the shapes emitted by
`langchain_anthropic.ChatAnthropic.astream()`.
"""

from __future__ import annotations

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
    """Mimic the `AIMessageChunk` shape: `content` + optional
    `usage_metadata` / `response_metadata` dicts. The stream endpoint
    reads these attributes defensively via `getattr`, so missing ones
    fall through cleanly."""

    def __init__(
        self,
        text: str,
        *,
        usage_metadata: dict[str, int] | None = None,
        response_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.content = text
        if usage_metadata is not None:
            self.usage_metadata = usage_metadata
        if response_metadata is not None:
            self.response_metadata = response_metadata


class _FakeLLM:
    def __init__(self, chunks: list[_FakeChunk]) -> None:
        self._chunks = chunks

    async def astream(self, messages: list[Any]) -> AsyncIterator[_FakeChunk]:
        for c in self._chunks:
            yield c


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Meta User",
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
async def test_stream_persists_metadata_from_chunks(client: AsyncClient) -> None:
    """The stream endpoint should stamp all five metadata columns when the
    provider returns usage + model details inside its chunks."""
    token = await _register_and_login(client, "meta-chunk@example.com")

    chunks = [
        _FakeChunk(
            "hello",
            response_metadata={"model": "claude-sonnet-4-6"},
        ),
        _FakeChunk(
            " world",
            usage_metadata={"input_tokens": 42, "output_tokens": 17},
            response_metadata={"model": "claude-sonnet-4-6"},
        ),
    ]
    fake_llm = _FakeLLM(chunks)

    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "explain recursion"},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp.aiter_bytes():
            pass

    # Fetch the persisted conversation and inspect the assistant row.
    convs = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = convs.json()[0]["id"]
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    messages = detail.json()["messages"]
    assistant = next(m for m in messages if m["role"] == "assistant")

    assert assistant["model"] == "claude-sonnet-4-6"
    assert assistant["input_tokens"] == 42
    assert assistant["output_tokens"] == 17
    # Latency is wall-clock: just assert non-null + total >= first.
    assert assistant["first_token_ms"] is not None
    assert assistant["total_duration_ms"] is not None
    assert assistant["first_token_ms"] >= 0
    assert assistant["total_duration_ms"] >= assistant["first_token_ms"]


@pytest.mark.asyncio
async def test_stream_falls_back_to_default_model(client: AsyncClient) -> None:
    """When the provider omits `response_metadata.model`, the persisted row
    still carries a model string (the configured default) so the hover
    popover has something to show instead of "—"."""
    token = await _register_and_login(client, "meta-default@example.com")

    # No response_metadata on any chunk + no usage_metadata.
    chunks = [_FakeChunk("plain"), _FakeChunk(" reply")]
    fake_llm = _FakeLLM(chunks)

    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": "hi"},
            headers={"Authorization": f"Bearer {token}"},
        )
        async for _ in resp.aiter_bytes():
            pass

    convs = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    conv_id = convs.json()[0]["id"]
    detail = await client.get(
        f"/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    messages = detail.json()["messages"]
    assistant = next(m for m in messages if m["role"] == "assistant")

    # Token counts absent when the provider doesn't report them.
    assert assistant["input_tokens"] is None
    assert assistant["output_tokens"] is None
    # Latency is always captured.
    assert assistant["first_token_ms"] is not None
    assert assistant["total_duration_ms"] is not None
    # Default-model fallback kicks in — we don't pin the exact string
    # (config varies) but it must be non-null + non-empty.
    assert assistant["model"] is not None
    assert len(assistant["model"]) > 0
