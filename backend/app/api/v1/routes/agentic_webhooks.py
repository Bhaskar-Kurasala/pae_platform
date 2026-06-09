"""Agentic-OS webhook routes — verified entry point for proactive
agent triggers from external systems.

Distinct from the legacy `app/api/v1/routes/webhooks.py` (which
serves the chat-stack stripe/github flows). Why two routers:

  • The legacy router uses `settings.github_token` (a PAT, not a
    webhook secret) for sig verify and silently skips when the
    secret is empty. New agentic primitives reject unsigned
    requests instead. Mixing the two on one mount path would
    blur the security contract.

  • The legacy router dispatches to legacy `BaseAgent` agents
    via direct module imports. The new router routes through
    `route_webhook` which fans out to every agentic agent
    subscribed via `@on_event`. Different dispatch model, different
    audit trail.

Per the D7b directive, signature verification runs as a FastAPI
DEPENDENCY (not a first-line call inside the handler body). That
gives us:
  • Visibility in the OpenAPI schema — anyone reading the route
    table sees "this endpoint requires a verified signature."
  • Middleware introspection — auth audits / rate-limiters can
    spot the dependency without parsing handler source.
  • Clean separation — handler body assumes the body is already
    verified and decoded.

The dependency reads the raw body once and passes it through to
the handler so we don't need the body twice (FastAPI's `Request`
body stream is single-use). The verified body is also returned
parsed-as-JSON for handler convenience.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.agents.primitives.proactive import (
    ProactiveDispatchResult,
    WebhookSignatureError,
    route_webhook,
    verify_github_signature,
    verify_stripe_signature,
)
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger().bind(layer="agentic_webhook")

router = APIRouter(
    prefix="/webhooks/agentic",
    tags=["agentic-webhooks"],
)


# ── Dependencies (signature verification) ──────────────────────────


class VerifiedGitHubPayload:
    """Container for a verified-and-parsed GitHub webhook body.

    The dependency builds and returns this. Handlers depend on it
    rather than rebuilding the verification logic per route.
    """

    def __init__(
        self,
        *,
        event: str,
        delivery_id: str,
        body: dict[str, Any],
    ) -> None:
        self.event = event
        self.delivery_id = delivery_id
        self.body = body


class VerifiedStripePayload:
    def __init__(
        self,
        *,
        event_type: str,
        delivery_id: str,
        body: dict[str, Any],
    ) -> None:
        self.event_type = event_type
        self.delivery_id = delivery_id
        self.body = body


async def verified_github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
    x_github_event: str = Header(default="", alias="X-GitHub-Event"),
    x_github_delivery: str = Header(default="", alias="X-GitHub-Delivery"),
) -> VerifiedGitHubPayload:
    """FastAPI dependency that:
      1. Reads the raw request body
      2. Verifies the X-Hub-Signature-256 header
      3. Parses the body as JSON
      4. Returns a VerifiedGitHubPayload the route handler consumes

    Sig failure → 401. Missing required header → 400. Bad JSON → 400.
    """
    if not x_github_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing X-GitHub-Event header",
        )
    if not x_github_delivery:
        # Without the delivery id we can't construct an idempotency
        # key — refusing the request is correct here. A delivery id
        # is on every real GitHub webhook.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing X-GitHub-Delivery header",
        )
    raw = await request.body()
    try:
        verify_github_signature(body=raw, signature_header=x_hub_signature_256)
    except WebhookSignatureError as exc:
        log.warning(
            "agentic_webhook.github.sig_failure",
            event_name=x_github_event,
            delivery_id=x_github_delivery,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid GitHub signature",
        ) from exc
    try:
        import json
        body = json.loads(raw or b"{}")
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook body is not valid JSON",
        ) from exc
    return VerifiedGitHubPayload(
        event=x_github_event,
        delivery_id=x_github_delivery,
        body=body,
    )


async def verified_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
) -> VerifiedStripePayload:
    raw = await request.body()
    try:
        verify_stripe_signature(body=raw, signature_header=stripe_signature)
    except WebhookSignatureError as exc:
        log.warning(
            "agentic_webhook.stripe.sig_failure", error=str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid Stripe signature",
        ) from exc
    try:
        import json
        body = json.loads(raw or b"{}")
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook body is not valid JSON",
        ) from exc
    delivery_id = body.get("id") or ""
    if not delivery_id:
        # Stripe events always have an `id` — refusing requests
        # without one prevents idempotency-key construction with
        # an empty value (which would silently skip the partial
        # unique guard).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stripe event body missing `id`",
        )
    return VerifiedStripePayload(
        event_type=str(body.get("type") or ""),
        delivery_id=str(delivery_id),
        body=body,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.post(
    "/github",
    summary="Verified GitHub webhook entry point for agentic flows",
)
async def receive_github_webhook(
    payload: VerifiedGitHubPayload = Depends(verified_github_webhook),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Routes a verified GitHub webhook to every subscribed
    agentic agent.

    Event-name mapping: GitHub's `X-GitHub-Event` header carries
    the high-level event ("push", "pull_request", ...). We
    namespace it as `github.<event>` so subscriptions like
    `@on_event("github.push")` work without having to think about
    headers.
    """
    event_name = f"github.{payload.event}"
    results: list[ProactiveDispatchResult] = await route_webhook(
        session=db,
        source="github",
        event_name=event_name,
        delivery_id=payload.delivery_id,
        payload=payload.body,
    )
    return {
        "event": event_name,
        "delivery_id": payload.delivery_id,
        "subscribers": len(results),
        "results": [
            {
                "audit_id": str(r.audit_id),
                "deduped": r.deduped,
                "status": r.status,
            }
            for r in results
        ],
    }


@router.post(
    "/stripe",
    summary="Verified Stripe webhook entry point for agentic flows",
)
async def receive_stripe_webhook(
    payload: VerifiedStripePayload = Depends(verified_stripe_webhook),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Routes a verified Stripe webhook to every subscribed
    agentic agent.

    Event-name mapping: Stripe's payload carries `type` like
    "checkout.session.completed". We namespace it as `stripe.<type>`
    so subscriptions read naturally:
      `@on_event("stripe.checkout.session.completed")`
    """
    event_name = f"stripe.{payload.event_type}"
    results: list[ProactiveDispatchResult] = await route_webhook(
        session=db,
        source="stripe",
        event_name=event_name,
        delivery_id=payload.delivery_id,
        payload=payload.body,
    )
    return {
        "event": event_name,
        "delivery_id": payload.delivery_id,
        "subscribers": len(results),
        "results": [
            {
                "audit_id": str(r.audit_id),
                "deduped": r.deduped,
                "status": r.status,
            }
            for r in results
        ],
    }
