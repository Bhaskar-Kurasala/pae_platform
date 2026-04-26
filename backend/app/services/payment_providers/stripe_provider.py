"""Stripe concrete implementation of ``PaymentProviderBase``.

This is a thin adapter that maps Stripe's PaymentIntent / Checkout / Refund
surface to the provider-agnostic dataclasses defined in ``base``. The legacy
``app/services/stripe_service.StripeService`` keeps its own checkout/portal API
for the existing ``routes/billing.py`` consumer; this provider is the new
abstraction the order/entitlement services will consume going forward.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import stripe
import structlog

from app.core.config import settings

from .base import (
    PaymentProviderBase,
    ProviderOrder,
    ProviderUnavailableError,
    RefundResult,
    WebhookEventEnvelope,
)

log = structlog.get_logger()


class StripeProvider(PaymentProviderBase):
    """Adapter around the official ``stripe`` SDK."""

    name = "stripe"

    def __init__(self) -> None:
        # Stripe API key is module-global; setting it on init is idempotent.
        stripe.api_key = settings.stripe_secret_key

    # ------------------------------------------------------------------
    # Order creation — mapped to PaymentIntent (the API surface that's the
    # closest equivalent to Razorpay's "create order then verify checkout"
    # two-step flow).
    # ------------------------------------------------------------------
    async def create_order(
        self,
        *,
        amount_cents: int,
        currency: str,
        receipt: str,
        notes: dict[str, str],
    ) -> ProviderOrder:
        def _create() -> dict[str, Any]:
            metadata: dict[str, str] = {"receipt": receipt, **notes}
            intent = stripe.PaymentIntent.create(  # type: ignore[attr-defined]
                amount=amount_cents,
                currency=currency.lower(),
                metadata=metadata,
            )
            return cast(dict[str, Any], dict(intent))

        try:
            response = await asyncio.to_thread(_create)
        except Exception as exc:
            log.warning("stripe.payment_intent.create_failed", error=str(exc))
            raise ProviderUnavailableError(
                f"Stripe payment intent create failed: {exc}"
            ) from exc

        log.info(
            "stripe.payment_intent.created",
            provider_order_id=response.get("id"),
            amount_cents=amount_cents,
            currency=currency,
        )
        return ProviderOrder(
            provider_order_id=str(response["id"]),
            amount_cents=int(response.get("amount", amount_cents)),
            currency=str(response.get("currency", currency)).upper(),
            raw_response=response,
        )

    # ------------------------------------------------------------------
    # Signatures
    # ------------------------------------------------------------------
    def verify_payment_signature(
        self,
        *,
        provider_order_id: str,
        provider_payment_id: str,
        signature: str,
    ) -> bool:
        """Documented no-op for Stripe.

        Stripe doesn't sign ``order_id|payment_id`` like Razorpay does. The
        Stripe redirect after Checkout already carries a signed ``session_id``
        (verified by ``stripe.checkout.Session.retrieve``), and the webhook is
        the auth boundary for asynchronous payment events. We return ``True``
        so the provider-agnostic flow stays uniform.
        """
        return True

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
        if not settings.stripe_webhook_secret:
            log.warning("stripe.webhook.secret_missing")
            return False
        try:
            stripe.Webhook.construct_event(  # type: ignore[attr-defined]
                raw_body, signature, settings.stripe_webhook_secret
            )
            return True
        except stripe.error.SignatureVerificationError:  # type: ignore[attr-defined]
            log.warning("stripe.webhook.signature_mismatch")
            return False
        except Exception as exc:  # malformed payload, etc.
            log.warning("stripe.webhook.construct_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Webhook parsing
    # ------------------------------------------------------------------
    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookEventEnvelope:
        # Stripe events:
        # {"id": "evt_…", "type": "checkout.session.completed",
        #  "data": {"object": {"id": "cs_…", "payment_intent": "pi_…", …}}}
        payload_dict: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        event_type = str(payload_dict.get("type", ""))
        provider_event_id = str(payload_dict.get("id", ""))

        obj = cast(
            dict[str, Any], (payload_dict.get("data") or {}).get("object") or {}
        )

        # Stripe's "order id" analogue is the PaymentIntent id; the "payment id"
        # for Checkout is also surfaced via ``payment_intent``. For refund
        # events the object IS a refund, so we pull ``payment_intent`` directly.
        related_order_id: str | None = obj.get("payment_intent") or obj.get("id")
        related_payment_id: str | None = obj.get("payment_intent")

        # If the object is itself a PaymentIntent (e.g. payment_intent.succeeded)
        # then ``id`` is the PaymentIntent id and ``payment_intent`` is absent.
        if obj.get("object") == "payment_intent":
            related_order_id = obj.get("id")
            related_payment_id = obj.get("id")

        return WebhookEventEnvelope(
            provider_event_id=provider_event_id,
            event_type=event_type,
            related_provider_order_id=related_order_id,
            related_provider_payment_id=related_payment_id,
            raw_payload=payload_dict,
        )

    # ------------------------------------------------------------------
    # Fetch + refund
    # ------------------------------------------------------------------
    async def fetch_payment(self, provider_payment_id: str) -> dict[str, Any]:
        def _fetch() -> dict[str, Any]:
            intent = stripe.PaymentIntent.retrieve(provider_payment_id)  # type: ignore[attr-defined]
            return cast(dict[str, Any], dict(intent))

        try:
            return await asyncio.to_thread(_fetch)
        except Exception as exc:
            log.warning(
                "stripe.payment.fetch_failed",
                provider_payment_id=provider_payment_id,
                error=str(exc),
            )
            raise ProviderUnavailableError(
                f"Stripe payment fetch failed: {exc}"
            ) from exc

    async def create_refund(
        self,
        *,
        provider_payment_id: str,
        amount_cents: int,
        notes: dict[str, str],
    ) -> RefundResult:
        def _refund() -> dict[str, Any]:
            refund = stripe.Refund.create(  # type: ignore[attr-defined]
                payment_intent=provider_payment_id,
                amount=amount_cents,
                metadata=notes,
            )
            return cast(dict[str, Any], dict(refund))

        try:
            response = await asyncio.to_thread(_refund)
        except Exception as exc:
            log.warning(
                "stripe.refund.create_failed",
                provider_payment_id=provider_payment_id,
                error=str(exc),
            )
            raise ProviderUnavailableError(
                f"Stripe refund failed: {exc}"
            ) from exc

        # Stripe refund status: "pending" | "succeeded" | "failed" | "canceled".
        # Normalise "succeeded" → "processed" so callers don't have to special-case
        # provider naming differences.
        raw_status = str(response.get("status", "pending"))
        normalised = "processed" if raw_status == "succeeded" else raw_status
        log.info(
            "stripe.refund.created",
            provider_refund_id=response.get("id"),
            status=normalised,
        )
        return RefundResult(
            provider_refund_id=str(response["id"]),
            status=normalised,
            raw_response=response,
        )
