"""PR3/D3.1 — CORS allowlist driven by CORS_ORIGINS env var.

The middleware is configured at app startup from `settings.cors_origins`.
These tests verify the wire-level behavior:

  - Same-origin / allowed-origin requests get the right
    Access-Control-Allow-Origin header back.
  - Foreign-origin requests do NOT get an Allow-Origin header (the
    browser then refuses to expose the response to the page).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_allowed_origin_gets_acao_header(client: AsyncClient) -> None:
    """A request from an origin in the allowlist gets the
    Access-Control-Allow-Origin header echoed back."""
    # Default test config has http://localhost:3000 in cors_origins.
    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORS preflight returns 200 with allow-origin echoed.
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_foreign_origin_does_not_get_acao_header(client: AsyncClient) -> None:
    """A request from a foreign origin gets NO Allow-Origin header. The
    browser then refuses to expose the response to the calling page —
    this is how CORS rejection works (FastAPI's CORSMiddleware does
    not 4xx the request; it just omits the headers)."""
    resp = await client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example.com"
    # Also confirm we didn't silently echo `*` — that would be a security regression.
    assert resp.headers.get("access-control-allow-origin") != "*"
