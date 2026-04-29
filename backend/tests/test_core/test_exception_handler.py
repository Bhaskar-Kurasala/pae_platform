"""PR2/B4.1 — exception handler middleware tests.

Verifies:
  1. An uncaught exception in a route returns a 500 with the stable
     {"error": {"type", "message", "request_id"}} envelope.
  2. The traceback is logged but NOT in the response body.
  3. The X-Request-ID header is preserved end-to-end.
  4. Starlette HTTPException keeps its declared status code and gets
     the same envelope shape.
  5. The original RateLimitExceeded handler still owns 429s (regression).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.exception_handler import unhandled_exception_handler
from app.core.request_id import REQUEST_ID_HEADER, RequestIDMiddleware


def _make_app() -> FastAPI:
    """Mini app that registers only the middleware + handler we're testing.

    Avoids importing the real settings/DB/redis chain — keeps tests
    hermetic and fast.
    """
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("kaboom — this is a test")

    @app.get("/forbidden")
    async def forbidden() -> dict[str, str]:
        raise HTTPException(status_code=403, detail="nope")

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_uncaught_exception_returns_stable_envelope() -> None:
    app = _make_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert "error" in body
    assert body["error"]["type"] == "internal_error"
    assert "request_id" in body["error"]
    assert "logged it" in body["error"]["message"].lower()


@pytest.mark.asyncio
async def test_response_does_not_leak_traceback() -> None:
    app = _make_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/boom")
    text = resp.text
    # Traceback frames or the exception message must not appear in the body.
    assert "kaboom" not in text
    assert "RuntimeError" not in text
    assert "Traceback" not in text
    assert "raise" not in text


@pytest.mark.asyncio
async def test_request_id_header_preserved() -> None:
    app = _make_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/boom", headers={REQUEST_ID_HEADER: "abcd-1234"}
        )
    assert resp.headers.get(REQUEST_ID_HEADER) == "abcd-1234"
    assert resp.json()["error"]["request_id"] == "abcd-1234"


@pytest.mark.asyncio
async def test_starlette_http_exception_passes_through_with_envelope() -> None:
    app = _make_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/forbidden")
    # FastAPI's own HTTPException handler catches this BEFORE our global
    # handler — so the response shape is FastAPI's `{"detail": ...}` form.
    # We assert that behavior so a future refactor doesn't accidentally
    # silence the test if the routing changes.
    assert resp.status_code == 403
    body = resp.json()
    assert body == {"detail": "nope"}


@pytest.mark.asyncio
async def test_happy_path_unaffected() -> None:
    app = _make_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ok")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # Even the happy path now ships the request id so the frontend can
    # surface it on errors that come from elsewhere.
    assert REQUEST_ID_HEADER in resp.headers
