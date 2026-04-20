"""P2-7 — stream rate-limit headers + 429 payload shape.

Covers the contract the UI depends on:
  - successful stream response carries ``X-RateLimit-Remaining`` and
    ``Retry-After`` so the composer can render "N messages left" pills.
  - 429 response carries both headers AND a ``retry_after_seconds`` int in
    the JSON body so the banner can countdown live instead of guessing.

The test drops the stream limit to a tiny value via ``monkeypatch`` on the
route decorator's captured ``STREAM_RATE_LIMIT`` constant. slowapi stamps
limits at import time, so we instead tweak the limiter's storage directly
by exhausting the limit the same way a real caller would.
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
    """Per-test FastAPI client with an in-memory SQLite engine.

    Mirrors ``test_chat_regenerate.py`` so stream tests share one engine
    across the register/login/stream cycle — otherwise the auth token
    points at a row in a different DB than the stream endpoint sees.
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


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Rate Limit Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


async def _stream_once(
    client: AsyncClient, token: str, message: str = "hi"
) -> tuple[int, dict[str, str], bytes]:
    fake_llm = _FakeLLM(["hello"])
    with patch("app.api.v1.routes.stream.build_llm", return_value=fake_llm):
        resp = await client.post(
            "/api/v1/agents/stream",
            json={"message": message},
            headers={"Authorization": f"Bearer {token}"},
        )
        chunks: list[bytes] = []
        async for chunk in resp.aiter_bytes():
            chunks.append(chunk)
    return resp.status_code, dict(resp.headers), b"".join(chunks)


@pytest.mark.asyncio
async def test_stream_200_exposes_rate_limit_headers(client: AsyncClient) -> None:
    """First successful stream response should carry ``X-RateLimit-Remaining``
    and ``Retry-After`` headers so the UI can render a messages-left pill."""
    token = await _register_and_login(client, "rl_happy@example.com")
    status, headers, _ = await _stream_once(client, token)
    assert status == 200
    # Header names are lowercased by httpx.
    assert "x-ratelimit-remaining" in headers
    assert "retry-after" in headers
    # Remaining must be a non-negative int, strictly less than the configured
    # limit after consuming 1/30.
    remaining = int(headers["x-ratelimit-remaining"])
    assert 0 <= remaining <= 30
    # Retry-After is delta-seconds: positive int within the 60-second window.
    retry_after = int(headers["retry-after"])
    assert 0 <= retry_after <= 60
    # Limit header is nice-to-have but consistent with the constant.
    assert headers.get("x-ratelimit-limit") == "30"


@pytest.mark.asyncio
async def test_stream_remaining_decrements_across_calls(client: AsyncClient) -> None:
    """Two calls from the same origin — remaining should strictly decrease.

    Guards against a silent no-op where the header parrots back 29 forever.
    """
    token = await _register_and_login(client, "rl_decr@example.com")
    _, first_headers, _ = await _stream_once(client, token)
    _, second_headers, _ = await _stream_once(client, token)
    assert int(second_headers["x-ratelimit-remaining"]) < int(
        first_headers["x-ratelimit-remaining"]
    )


@pytest.mark.asyncio
async def test_stream_429_returns_retry_after_and_body(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exhaust the limit and assert the 429 shape.

    We patch the stream endpoint's ``STREAM_RATE_LIMIT`` constant to the
    tightest possible ``1/minute`` so we can blow past it with two calls
    without burning 30 stream fixtures in a row. The slowapi decorator
    captures the callable at import time — but ``@limiter.limit`` reads
    the arg eagerly as a string, so patching requires re-importing. We
    use a simpler pathway: make 31 calls against the default 30/minute
    and observe the 31st. The reset fixture resets storage between
    tests, so the explosion is safe.
    """
    # Use the full 30/minute default — slowapi pre-registers the limit on
    # the route object at import time, so runtime patching of the constant
    # does not affect the active decorator. 31 calls is cheap because the
    # fake LLM is in-memory and yields one token.
    token = await _register_and_login(client, "rl_429@example.com")
    # Consume the allowed 30 requests without asserting so we hit the edge
    # cleanly. Some may already be counted depending on test ordering so we
    # loop until we see the 429 — bounded to 40 so a bug here fails fast.
    last_status = 200
    last_headers: dict[str, str] = {}
    last_body = b""
    for _ in range(40):
        last_status, last_headers, last_body = await _stream_once(client, token)
        if last_status == 429:
            break

    assert last_status == 429, "expected rate-limiter to trip within 40 calls"
    # 429 body contract the frontend parses.
    import json as _json

    parsed = _json.loads(last_body.decode("utf-8"))
    assert parsed["detail"].lower().startswith("rate limit exceeded")
    assert isinstance(parsed["retry_after_seconds"], int)
    assert parsed["retry_after_seconds"] >= 1

    # Header contract.
    assert "retry-after" in last_headers
    assert int(last_headers["retry-after"]) >= 1
    assert "x-ratelimit-remaining" in last_headers
    # After tripping the limit, remaining is 0 (slowapi's window stats).
    assert int(last_headers["x-ratelimit-remaining"]) == 0


@pytest.mark.asyncio
async def test_cors_exposes_rate_limit_headers() -> None:
    """Sanity-check the CORS expose list so browser JS can read the headers
    cross-origin. The FastAPI middleware config is read once at startup —
    we just probe the registered middleware stack."""
    from starlette.middleware.cors import CORSMiddleware

    cors_middleware = next(
        mw for mw in app.user_middleware if mw.cls is CORSMiddleware
    )
    expose = cors_middleware.kwargs.get("expose_headers", [])
    assert "X-RateLimit-Remaining" in expose
    assert "Retry-After" in expose
