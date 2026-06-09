"""Razorpay concrete implementation of ``PaymentProviderBase``.

The Razorpay Python SDK is synchronous, so every network call is wrapped in
``asyncio.to_thread`` to keep the FastAPI event loop unblocked.

Conventions:
* Amounts are always in **paise** (the smallest INR unit) on the wire — the
  same convention as Stripe cents. The dataclasses keep the ``_cents`` suffix
  for cross-provider consistency.
* Signature verification methods return ``bool`` (False on mismatch) rather
  than re-raising the SDK's ``SignatureVerificationError`` — that's the
  contract documented in ``base.PaymentProviderBase``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import razorpay  # type: ignore[import-untyped]
import structlog
from razorpay.errors import (  # type: ignore[import-untyped]
    SignatureVerificationError,
)

from app.core.config import settings

from .base import (
    PaymentProviderBase,
    ProviderOrder,
    ProviderUnavailableError,
    RefundResult,
    WebhookEventEnvelope,
)

log = structlog.get_logger()


class RazorpayProvider(PaymentProviderBase):
    """Adapter around the official ``razorpay`` SDK."""

    name = "razorpay"

    def __init__(self) -> None:
        # Auth tuple is (key_id, key_secret); Razorpay's verify_payment_signature
        # reads the secret straight off ``client.auth[1]`` so it MUST be set
        # even when we only intend to call the verify methods.
        self._client = razorpay.Client(
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
        )

    # ------------------------------------------------------------------
    # Order creation
    # ------------------------------------------------------------------
    async def create_order(
        self,
        *,
        amount_cents: int,
        currency: str,
        receipt: str,
        notes: dict[str, str],
    ) -> ProviderOrder:
        payload: dict[str, Any] = {
            "amount": amount_cents,
            "currency": currency,
            "receipt": receipt,
            "notes": notes,
        }
        try:
            response = await asyncio.to_thread(self._client.order.create, data=payload)
        except Exception as exc:  # SDK raises GatewayError/ServerError; normalise.
            log.warning("razorpay.order.create_failed", error=str(exc))
            raise ProviderUnavailableError(
                f"Razorpay order create failed: {exc}"
            ) from exc

        log.info(
            "razorpay.order.created",
            provider_order_id=response.get("id"),
            amount_cents=amount_cents,
            currency=currency,
        )
        return ProviderOrder(
            provider_order_id=str(response["id"]),
            amount_cents=int(response.get("amount", amount_cents)),
            currency=str(response.get("currency", currency)),
            raw_response=dict(response),
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
        params = {
            "razorpay_order_id": provider_order_id,
            "razorpay_payment_id": provider_payment_id,
            "razorpay_signature": signature,
        }
        try:
            self._client.utility.verify_payment_signature(params)
            return True
        except SignatureVerificationError:
            log.warning(
                "razorpay.payment_signature.mismatch",
                provider_order_id=provider_order_id,
                provider_payment_id=provider_payment_id,
            )
            return False

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
        if not settings.razorpay_webhook_secret:
            log.warning("razorpay.webhook.secret_missing")
            return False
        try:
            self._client.utility.verify_webhook_signature(
                raw_body.decode("utf-8"),
                signature,
                settings.razorpay_webhook_secret,
            )
            return True
        except SignatureVerificationError:
            log.warning("razorpay.webhook.signature_mismatch")
            return False

    # ------------------------------------------------------------------
    # Webhook parsing
    # ------------------------------------------------------------------
    def parse_webhook_event(self, *, raw_body: bytes) -> WebhookEventEnvelope:
        # Razorpay events look like:
        # {
        #   "id": "evt_…",
        #   "event": "payment.captured",
        #   "payload": {
        #     "payment": {"entity": {"id": "pay_…", "order_id": "order_…", …}},
        #     "order":   {"entity": {"id": "order_…", …}}
        #   }
        # }
        payload_dict: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        event_type = str(payload_dict.get("event", ""))
        provider_event_id = str(payload_dict.get("id", ""))

        nested = cast(dict[str, Any], payload_dict.get("payload") or {})
        payment_entity = cast(
            dict[str, Any],
            (nested.get("payment") or {}).get("entity") or {},
        )
        order_entity = cast(
            dict[str, Any],
            (nested.get("order") or {}).get("entity") or {},
        )
        refund_entity = cast(
            dict[str, Any],
            (nested.get("refund") or {}).get("entity") or {},
        )

        related_payment_id: str | None = (
            payment_entity.get("id") or refund_entity.get("payment_id")
        )
        related_order_id: str | None = (
            order_entity.get("id")
            or payment_entity.get("order_id")
            or refund_entity.get("order_id")
        )

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
        try:
            response = await asyncio.to_thread(
                self._client.payment.fetch, provider_payment_id
            )
        except Exception as exc:
            log.warning(
                "razorpay.payment.fetch_failed",
                provider_payment_id=provider_payment_id,
                error=str(exc),
            )
            raise ProviderUnavailableError(
                f"Razorpay payment fetch failed: {exc}"
            ) from exc
        return dict(response)

    async def create_refund(
        self,
        *,
        provider_payment_id: str,
        amount_cents: int,
        notes: dict[str, str],
    ) -> RefundResult:
        data: dict[str, Any] = {"amount": amount_cents, "notes": notes}
        try:
            response = await asyncio.to_thread(
                self._client.payment.refund, provider_payment_id, data
            )
        except Exception as exc:
            log.warning(
                "razorpay.refund.create_failed",
                provider_payment_id=provider_payment_id,
                error=str(exc),
            )
            raise ProviderUnavailableError(
                f"Razorpay refund failed: {exc}"
            ) from exc

        # Razorpay refund status values: "pending" | "processed" | "failed".
        status = str(response.get("status", "pending"))
        log.info(
            "razorpay.refund.created",
            provider_refund_id=response.get("id"),
            status=status,
        )
        return RefundResult(
            provider_refund_id=str(response["id"]),
            status=status,
            raw_response=dict(response),
        )
