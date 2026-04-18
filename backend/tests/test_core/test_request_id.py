import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_request_id_header_is_echoed(client: AsyncClient) -> None:
    custom_id = "test-request-12345"
    resp = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.headers.get("X-Request-ID") == custom_id


async def test_request_id_generated_when_absent(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert "X-Request-ID" in resp.headers
    # UUID4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx (36 chars)
    assert len(resp.headers["X-Request-ID"]) == 36
