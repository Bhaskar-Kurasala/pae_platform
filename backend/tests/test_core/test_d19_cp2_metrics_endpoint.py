"""D19.1 CP2 — /metrics endpoint smoke test.

Verifies the four behaviours of the auth-gated scrape endpoint:

  1. With METRICS_USERNAME + METRICS_PASSWORD set, valid Basic auth
     returns 200 + Prometheus exposition payload.
  2. Same env, wrong password → 401 + WWW-Authenticate header.
  3. Same env, no Authorization header → 401.
  4. Either env var unset → 503 (fail-closed default).

Builds an isolated FastAPI app (just the metrics router + middleware)
so the test is independent of the platform's full route graph.
"""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.routes.metrics import router as metrics_router


@pytest.fixture
def metrics_app() -> FastAPI:
    """A minimal FastAPI carrying only the /metrics router."""
    app = FastAPI()
    app.include_router(metrics_router)
    return app


def _basic_auth(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


async def test_metrics_endpoint_503_when_unconfigured(
    metrics_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No METRICS_USERNAME / METRICS_PASSWORD → fail-closed 503."""
    monkeypatch.delenv("METRICS_USERNAME", raising=False)
    monkeypatch.delenv("METRICS_PASSWORD", raising=False)

    async with AsyncClient(
        transport=ASGITransport(app=metrics_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 503


async def test_metrics_endpoint_401_without_auth_header(
    metrics_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured but no Authorization header → 401 + WWW-Authenticate."""
    monkeypatch.setenv("METRICS_USERNAME", "scraper")
    monkeypatch.setenv("METRICS_PASSWORD", "s3cret")

    async with AsyncClient(
        transport=ASGITransport(app=metrics_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").lower().startswith("basic")


async def test_metrics_endpoint_401_with_wrong_password(
    metrics_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured + wrong creds → 401."""
    monkeypatch.setenv("METRICS_USERNAME", "scraper")
    monkeypatch.setenv("METRICS_PASSWORD", "s3cret")

    async with AsyncClient(
        transport=ASGITransport(app=metrics_app), base_url="http://test"
    ) as ac:
        resp = await ac.get(
            "/metrics", headers={"Authorization": _basic_auth("scraper", "wrong")}
        )
    assert resp.status_code == 401


async def test_metrics_endpoint_200_with_valid_auth(
    metrics_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured + correct creds → 200 + Prometheus exposition format."""
    monkeypatch.setenv("METRICS_USERNAME", "scraper")
    monkeypatch.setenv("METRICS_PASSWORD", "s3cret")

    async with AsyncClient(
        transport=ASGITransport(app=metrics_app), base_url="http://test"
    ) as ac:
        resp = await ac.get(
            "/metrics", headers={"Authorization": _basic_auth("scraper", "s3cret")}
        )
    assert resp.status_code == 200
    body = resp.text
    # Substrate sanity: at least one D-D canonical metric registered.
    assert "aicareeros_agent_invocations" in body
    assert "# HELP" in body
    assert "# TYPE" in body


async def test_metrics_endpoint_401_with_malformed_basic_header(
    metrics_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured + malformed Basic value → 401, no crash."""
    monkeypatch.setenv("METRICS_USERNAME", "scraper")
    monkeypatch.setenv("METRICS_PASSWORD", "s3cret")

    async with AsyncClient(
        transport=ASGITransport(app=metrics_app), base_url="http://test"
    ) as ac:
        resp = await ac.get(
            "/metrics", headers={"Authorization": "Basic not-base64-content!!!"}
        )
    assert resp.status_code == 401
