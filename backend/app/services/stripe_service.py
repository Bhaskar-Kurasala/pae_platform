# Stripe payment service — wraps stripe SDK for checkout, webhooks, customer portal
import asyncio
import datetime
from typing import Any

import stripe
import structlog

from app.core.config import settings

log = structlog.get_logger()


class StripeService:
    """Thin async wrapper around the Stripe SDK."""

    def __init__(self) -> None:
        stripe.api_key = settings.stripe_secret_key

    async def create_checkout_session(
        self,
        user_id: str,
        course_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create a Stripe Checkout session and return the session URL.

        Metadata contains user_id and course_id so the webhook handler can
        look up the correct user and enrol them after payment.
        """

        def _create() -> str:
            session = stripe.checkout.Session.create(  # type: ignore[attr-defined]
                mode="payment",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"user_id": user_id, "course_id": course_id},
            )
            url: str = session.url or ""
            return url

        url = await asyncio.to_thread(_create)
        log.info(
            "stripe.checkout_session.created",
            user_id=user_id,
            course_id=course_id,
            price_id=price_id,
        )
        return url

    async def handle_webhook(self, payload: bytes, sig_header: str) -> dict[str, Any]:
        """Verify the Stripe webhook signature and return the parsed event.

        Returns a dict with ``event_type`` and ``data`` keys.
        Raises ``ValueError`` if the signature is invalid or the secret is
        not configured.
        """
        if not settings.stripe_webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")

        def _construct() -> stripe.Event:  # type: ignore[name-defined]
            return stripe.Webhook.construct_event(  # type: ignore[attr-defined]
                payload, sig_header, settings.stripe_webhook_secret
            )

        try:
            event = await asyncio.to_thread(_construct)
        except stripe.error.SignatureVerificationError as exc:  # type: ignore[attr-defined]
            log.warning("stripe.webhook.signature_invalid", error=str(exc))
            raise ValueError("Invalid Stripe webhook signature") from exc

        log.info("stripe.webhook.received", event_type=event["type"])
        return {
            "event_type": event["type"],
            "data": dict(event["data"]["object"]),
        }

    async def create_customer_portal_session(
        self, customer_id: str, return_url: str
    ) -> str:
        """Create a Stripe Customer Portal session and return the portal URL."""

        def _create() -> str:
            session = stripe.billing_portal.Session.create(  # type: ignore[attr-defined]
                customer=customer_id,
                return_url=return_url,
            )
            url: str = session.url or ""
            return url

        url = await asyncio.to_thread(_create)
        log.info("stripe.portal_session.created", customer_id=customer_id)
        return url

    def get_price_id(self, tier: str) -> str:
        """Return the Stripe price ID for the given subscription tier.

        Falls back to hardcoded test IDs when env vars are not set.
        """
        if tier == "pro":
            return settings.stripe_pro_price_id or "price_pro_test"
        if tier == "team":
            return settings.stripe_team_price_id or "price_team_test"
        raise ValueError(f"Unknown tier: {tier!r}. Expected 'pro' or 'team'.")

    async def get_subscription_info(
        self, stripe_customer_id: str
    ) -> dict[str, Any]:
        """Retrieve the most recent subscription for a Stripe customer.

        Returns a dict with ``tier``, ``status``, and ``current_period_end``
        suitable for the ``SubscriptionInfo`` schema.
        """

        def _fetch() -> dict[str, Any]:
            subscriptions = stripe.Subscription.list(  # type: ignore[attr-defined]
                customer=stripe_customer_id, limit=1, status="all"
            )
            items = subscriptions.get("data", [])
            if not items:
                return {"tier": "free", "status": "active", "current_period_end": None}

            sub = items[0]
            price_id: str = sub["items"]["data"][0]["price"]["id"]

            if price_id == settings.stripe_pro_price_id:
                tier = "pro"
            elif price_id == settings.stripe_team_price_id:
                tier = "team"
            else:
                tier = "pro"  # unknown price — treat as pro

            period_end: datetime.datetime | None = None
            if sub.get("current_period_end"):
                period_end = datetime.datetime.fromtimestamp(
                    sub["current_period_end"], tz=datetime.UTC
                )

            return {
                "tier": tier,
                "status": sub.get("status", "unknown"),
                "current_period_end": period_end,
            }

        return await asyncio.to_thread(_fetch)
