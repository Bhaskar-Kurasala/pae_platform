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
