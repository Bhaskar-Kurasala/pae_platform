import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_health_live(client: AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_health_ready(client: AsyncClient) -> None:
    resp = await client.get("/health/ready")
    # 200 if all deps healthy, 503 if any degraded — both are acceptable
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "status" in data
    assert "checks" in data
    assert "db" in data["checks"]
    assert "redis" in data["checks"]


async def test_health_original_still_works(client: AsyncClient) -> None:
    """The original /health endpoint must stay working (backwards compatibility)."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_health_version_returns_triple(client: AsyncClient) -> None:
    """PR3/C6.2 — /health/version exposes commit_sha, build_time, env."""
    resp = await client.get("/health/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "commit_sha" in data
    assert "build_time" in data
    assert "env" in data
    # Triple is always non-empty — even without build args we fall back
    # to sentinels so on-call can spot a non-CI build at a glance.
    assert data["commit_sha"]
    assert data["build_time"]
    assert data["env"]
