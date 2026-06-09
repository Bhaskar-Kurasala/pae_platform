"""PR2/A4.1 — `@deprecated` route decorator + middleware tests.

Verifies:
  1. The `Deprecation: true` header lands on every response from a
     decorated route.
  2. `Sunset:` and `Deprecation-Reason:` show up when configured.
  3. structlog emits a `deprecated_endpoint_called` warning per call.
  4. The decorated handler's actual return value is unchanged.
  5. The middleware leaves non-deprecated routes alone.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api._deprecated import DeprecationHeaderMiddleware, deprecated


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(DeprecationHeaderMiddleware)
    router = APIRouter()

    @router.get("/with-meta")
    @deprecated(sunset="2026-07-01", reason="superseded by /v2/path")
    async def with_meta() -> dict[str, str]:
        return {"hello": "world"}

    @router.get("/no-meta")
    @deprecated()
    async def no_meta() -> dict[str, str]:
        return {"ok": "true"}

    @router.get("/fresh")
    async def fresh() -> dict[str, str]:
        return {"healthy": "yes"}

    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_deprecation_header_set() -> None:
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/with-meta")
    assert resp.status_code == 200
    assert resp.headers.get("Deprecation") == "true"


@pytest.mark.asyncio
async def test_sunset_and_reason_headers_set() -> None:
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/with-meta")
    assert resp.headers.get("Sunset") == "2026-07-01"
    assert resp.headers.get("Deprecation-Reason") == "superseded by /v2/path"


@pytest.mark.asyncio
async def test_no_meta_only_sets_deprecation_header() -> None:
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/no-meta")
    assert resp.headers.get("Deprecation") == "true"
    assert "Sunset" not in resp.headers
    assert "Deprecation-Reason" not in resp.headers


@pytest.mark.asyncio
async def test_handler_return_value_unchanged() -> None:
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/with-meta")
    assert resp.json() == {"hello": "world"}


@pytest.mark.asyncio
async def test_non_deprecated_route_untouched() -> None:
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/fresh")
    assert resp.status_code == 200
    assert "Deprecation" not in resp.headers
    assert "Sunset" not in resp.headers


@pytest.mark.asyncio
async def test_emits_deprecated_endpoint_called_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Confirms a structlog warning fires per call so we can grep
    production logs to find live callers of a sunset endpoint.

    The project's structlog config (see `app/core/log_config.py`) renders
    JSON directly to stdout, so we capture stdout rather than stdlib
    logging — that's where the structured event actually lands in prod
    too. Asserting against the JSON body keeps the test honest.
    """
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/with-meta")

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "deprecated_endpoint_called" in combined
    assert "2026-07-01" in combined
    assert "superseded by /v2/path" in combined
