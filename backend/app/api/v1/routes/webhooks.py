import hashlib
import hmac
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import settings

log = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_github_signature(body: bytes, signature: str) -> None:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    secret = settings.github_token.encode()
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub signature",
        )


def _verify_stripe_signature(body: bytes, signature: str) -> None:
    """Verify Stripe webhook signature (simplified — use stripe SDK in prod)."""
    if not settings.stripe_webhook_secret:
        return
    parts = {p.split("=")[0]: p.split("=")[1] for p in signature.split(",") if "=" in p}
    timestamp = parts.get("t", "")
    payload = f"{timestamp}.{body.decode()}"
    expected = hmac.new(
        settings.stripe_webhook_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    v1 = parts.get("v1", "")
    if not hmac.compare_digest(expected, v1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Stripe signature",
        )


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
) -> dict[str, str]:
    body = await request.body()
    if x_hub_signature_256:
        _verify_github_signature(body, x_hub_signature_256)
    payload: dict[str, Any] = await request.json()
    log.info(
        "webhook.github", gh_event=x_github_event, repo=payload.get("repository", {}).get("name")
    )
    return {"status": "received", "event": x_github_event}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default=""),
) -> dict[str, str]:
    body = await request.body()
    if stripe_signature and settings.stripe_webhook_secret:
        _verify_stripe_signature(body, stripe_signature)
    payload: dict[str, Any] = await request.json()
    event_type: str = payload.get("type", "unknown")
    log.info("webhook.stripe", stripe_event=event_type)
    return {"status": "received", "event": event_type}
