import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_github_webhook_no_signature(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/webhooks/github",
        json={"action": "push", "repository": {"name": "test-repo"}},
        headers={"X-GitHub-Event": "push"},
    )
    assert resp.status_code == 200
    assert resp.json()["event"] == "push"


@pytest.mark.asyncio
async def test_github_webhook_bad_signature(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/webhooks/github",
        json={"action": "push"},
        headers={
            "X-Hub-Signature-256": "sha256=badsignature",
            "X-GitHub-Event": "push",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stripe_webhook_no_secret_configured(client: AsyncClient) -> None:
    """When STRIPE_WEBHOOK_SECRET is empty the endpoint must refuse all requests."""
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        json={"type": "payment_intent.succeeded", "data": {}},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Stripe webhook not configured"
