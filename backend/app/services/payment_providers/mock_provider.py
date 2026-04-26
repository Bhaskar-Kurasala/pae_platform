"""MockProvider — deterministic in-memory provider for dev + tests.

Used automatically when:
  * `name == "mock"` is requested explicitly, OR
  * The factory falls back because Razorpay credentials are unconfigured
    (`settings.razorpay_key_id` / `razorpay_key_secret` empty) AND the
    environment is not "production".

It honors the same `PaymentProviderBase` contract as the real providers,
mints predictable provider order/payment ids (`mock_order_<8hex>`,
`mock_pay_<8hex>`), and uses HMAC-SHA256 with a known dev secret to
sign payments and webhooks so tests can construct valid signatures.

NEVER load this in a production process; the factory blocks it via the
`environment` config when env=`production`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any

import structlog

from .base import (
    PaymentProviderBase,
    ProviderOrder,
    RefundResult,
    SignatureMismatchError,
    WebhookEventEnvelope,
)

log = structlog.get_logger()

# A non-secret, fixed dev secret. Used to compute deterministic signatures
# for tests + Playwright E2E. Real environments must use the real Razorpay
# webhook secret via `settings.razorpay_webhook_secret`.
DEV_HMAC_SECRET = "dev-mock-secret-not-for-production"


def _hmac_sha256_hex(message: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class MockProvider(PaymentProviderBase):
    """Deterministic stand-in for a real payment gateway."""

    name = "mock"

    async def create_order(
        self,
        *,
        amount_cents: int,
        currency: str,
        receipt: str,
        notes: dict[str, str],
    ) -> ProviderOrder:
        provider_order_id = f"mock_order_{secrets.token_hex(6)}"
        log.info(
            "mock_provider.create_order",
            provider_order_id=provider_order_id,
            amount_cents=amount_cents,
            currency=currency,
        )
        return ProviderOrder(
            provider_order_id=provider_order_id,
            amount_cents=amount_cents,
            currency=currency,
            raw_response={
                "id": provider_order_id,
                "amount": amount_cents,
                "currency": currency,
                "receipt": receipt,
                "notes": notes,
                "status": "created",
            },
        )

    def verify_payment_signature(
        self,
        *,
        provider_order_id: str,
        provider_payment_id: str,
        signature: str,
    ) -> bool:
        # Razorpay's signature scheme: HMAC_SHA256(order_id|payment_id, secret).
        message = f"{provider_order_id}|{provider_payment_id}"
        expected = _hmac_sha256_hex(message, DEV_HMAC_SECRET)
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(
        self, *, raw_body: bytes, signature: str
    ) -> bool:
        expected = _hmac_sha256_hex(
            raw_body.decode("utf-8"), DEV_HMAC_SECRET
        )
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(
        self, *, raw_body: bytes
    ) -> WebhookEventEnvelope:
        try:
            payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SignatureMismatchError(
                f"Could not parse mock webhook body: {exc}"
            ) from exc
        provider_event_id = str(
            payload.get("id", f"mock_evt_{uuid.uuid4().hex[:8]}")
        )
        event_type = str(payload.get("event", "payment.captured"))
        related_order_id = (
            payload.get("payload", {})
            .get("order", {})
            .get("entity", {})
            .get("id")
            or payload.get("payload", {})
            .get("payment", {})
            .get("entity", {})
            .get("order_id")
        )
        related_payment_id = (
            payload.get("payload", {})
            .get("payment", {})
            .get("entity", {})
            .get("id")
        )
        return WebhookEventEnvelope(
            provider_event_id=provider_event_id,
            event_type=event_type,
            related_provider_order_id=related_order_id,
            related_provider_payment_id=related_payment_id,
            raw_payload=payload,
        )

    async def fetch_payment(self, provider_payment_id: str) -> dict[str, Any]:
        return {
            "id": provider_payment_id,
            "status": "captured",
            "amount": 0,  # caller can override; mock doesn't track
            "currency": "INR",
        }

    async def create_refund(
        self,
        *,
        provider_payment_id: str,
        amount_cents: int,
        notes: dict[str, str],
    ) -> RefundResult:
        provider_refund_id = f"mock_rfnd_{secrets.token_hex(6)}"
        return RefundResult(
            provider_refund_id=provider_refund_id,
            status="processed",
            raw_response={
                "id": provider_refund_id,
                "payment_id": provider_payment_id,
                "amount": amount_cents,
                "notes": notes,
                "status": "processed",
            },
        )


def sign_payment(provider_order_id: str, provider_payment_id: str) -> str:
    """Test/dev helper: produce the signature the mock provider expects."""
    return _hmac_sha256_hex(
        f"{provider_order_id}|{provider_payment_id}", DEV_HMAC_SECRET
    )


def sign_webhook(raw_body: bytes) -> str:
    """Test/dev helper: produce the signature for a mock webhook body."""
    return _hmac_sha256_hex(raw_body.decode("utf-8"), DEV_HMAC_SECRET)
