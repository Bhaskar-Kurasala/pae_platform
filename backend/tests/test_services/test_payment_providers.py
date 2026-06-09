"""Unit tests for the payment_providers abstraction.

Mocks the underlying SDK so these tests run without network access. We
exercise the provider-agnostic envelope shapes here; integration with the
real Razorpay/Stripe APIs is covered separately by the order/webhook E2E
suite.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.payment_providers import (
    ProviderOrder,
    RefundResult,
    WebhookEventEnvelope,
    get_provider,
)
from app.services.payment_providers.razorpay_provider import RazorpayProvider
from app.services.payment_providers.stripe_provider import StripeProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def razorpay_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Patch settings to use deterministic Razorpay creds for signature tests."""
    secret = "test_secret_known_value"
    from app.services.payment_providers import razorpay_provider as rp_mod

    monkeypatch.setattr(rp_mod.settings, "razorpay_key_id", "rzp_test_key", raising=False)
    monkeypatch.setattr(rp_mod.settings, "razorpay_key_secret", secret, raising=False)
    monkeypatch.setattr(
        rp_mod.settings, "razorpay_webhook_secret", secret, raising=False
    )
    return secret


def _hmac_hex(secret: str, message: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# ---------------------------------------------------------------------------
# Razorpay — create_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_razorpay_create_order_calls_sdk_with_paise(
    razorpay_secret: str,
) -> None:
    """create_order must forward amount_cents (paise) and return a ProviderOrder."""
    fake_response: dict[str, Any] = {
        "id": "order_ABC123",
        "amount": 49900,  # ₹499.00 in paise
        "currency": "INR",
        "receipt": "rcpt_42",
        "status": "created",
    }

    provider = RazorpayProvider()
    fake_order_resource = MagicMock()
    fake_order_resource.create.return_value = fake_response

    with patch.object(provider._client, "order", fake_order_resource):
        result = await provider.create_order(
            amount_cents=49900,
            currency="INR",
            receipt="rcpt_42",
            notes={"course_id": "course-123"},
        )

    fake_order_resource.create.assert_called_once_with(
        data={
            "amount": 49900,
            "currency": "INR",
            "receipt": "rcpt_42",
            "notes": {"course_id": "course-123"},
        }
    )
    assert isinstance(result, ProviderOrder)
    assert result.provider_order_id == "order_ABC123"
    assert result.amount_cents == 49900
    assert result.currency == "INR"
    assert result.raw_response["status"] == "created"


# ---------------------------------------------------------------------------
# Razorpay — verify_payment_signature
# ---------------------------------------------------------------------------


def test_razorpay_verify_payment_signature_known_good(razorpay_secret: str) -> None:
    """A signature computed with the known secret over `order|payment` verifies."""
    order_id = "order_X"
    payment_id = "pay_Y"
    sig = _hmac_hex(razorpay_secret, f"{order_id}|{payment_id}")

    provider = RazorpayProvider()
    assert (
        provider.verify_payment_signature(
            provider_order_id=order_id,
            provider_payment_id=payment_id,
            signature=sig,
        )
        is True
    )


def test_razorpay_verify_payment_signature_tampered(razorpay_secret: str) -> None:
    provider = RazorpayProvider()
    assert (
        provider.verify_payment_signature(
            provider_order_id="order_X",
            provider_payment_id="pay_Y",
            signature="deadbeef" * 8,
        )
        is False
    )


# ---------------------------------------------------------------------------
# Razorpay — verify_webhook_signature
# ---------------------------------------------------------------------------


def test_razorpay_verify_webhook_signature_correct(razorpay_secret: str) -> None:
    body = b'{"event":"payment.captured","id":"evt_1"}'
    sig = _hmac_hex(razorpay_secret, body.decode("utf-8"))

    provider = RazorpayProvider()
    assert provider.verify_webhook_signature(raw_body=body, signature=sig) is True


def test_razorpay_verify_webhook_signature_tampered(razorpay_secret: str) -> None:
    body = b'{"event":"payment.captured","id":"evt_1"}'
    provider = RazorpayProvider()
    assert (
        provider.verify_webhook_signature(raw_body=body, signature="not-a-real-sig")
        is False
    )


# ---------------------------------------------------------------------------
# Razorpay — parse_webhook_event
# ---------------------------------------------------------------------------


def test_razorpay_parse_webhook_event_payment_captured(razorpay_secret: str) -> None:
    body_dict: dict[str, Any] = {
        "id": "evt_payment_captured_1",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_abc",
                    "order_id": "order_xyz",
                    "amount": 49900,
                    "currency": "INR",
                    "status": "captured",
                }
            },
            "order": {"entity": {"id": "order_xyz", "amount": 49900}},
        },
    }
    raw = json.dumps(body_dict).encode("utf-8")

    provider = RazorpayProvider()
    envelope = provider.parse_webhook_event(raw_body=raw)

    assert isinstance(envelope, WebhookEventEnvelope)
    assert envelope.event_type == "payment.captured"
    assert envelope.provider_event_id == "evt_payment_captured_1"
    assert envelope.related_provider_order_id == "order_xyz"
    assert envelope.related_provider_payment_id == "pay_abc"
    assert envelope.raw_payload["payload"]["payment"]["entity"]["status"] == "captured"


def test_razorpay_parse_webhook_event_refund_processed(razorpay_secret: str) -> None:
    body_dict: dict[str, Any] = {
        "id": "evt_refund_1",
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_abc",
                    "payment_id": "pay_abc",
                    "order_id": "order_xyz",
                    "amount": 10000,
                    "status": "processed",
                }
            }
        },
    }
    raw = json.dumps(body_dict).encode("utf-8")

    provider = RazorpayProvider()
    envelope = provider.parse_webhook_event(raw_body=raw)

    assert envelope.event_type == "refund.processed"
    assert envelope.provider_event_id == "evt_refund_1"
    assert envelope.related_provider_payment_id == "pay_abc"
    assert envelope.related_provider_order_id == "order_xyz"


# ---------------------------------------------------------------------------
# Razorpay — fetch_payment + create_refund
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_razorpay_fetch_payment_returns_dict(razorpay_secret: str) -> None:
    fake_payment = {"id": "pay_abc", "status": "captured", "amount": 49900}
    provider = RazorpayProvider()
    fake_payment_resource = MagicMock()
    fake_payment_resource.fetch.return_value = fake_payment

    with patch.object(provider._client, "payment", fake_payment_resource):
        result = await provider.fetch_payment("pay_abc")

    fake_payment_resource.fetch.assert_called_once_with("pay_abc")
    assert result == fake_payment


@pytest.mark.asyncio
async def test_razorpay_create_refund_returns_refund_result(
    razorpay_secret: str,
) -> None:
    fake_refund = {"id": "rfnd_abc", "status": "processed", "amount": 10000}
    provider = RazorpayProvider()
    fake_payment_resource = MagicMock()
    fake_payment_resource.refund.return_value = fake_refund

    with patch.object(provider._client, "payment", fake_payment_resource):
        result = await provider.create_refund(
            provider_payment_id="pay_abc",
            amount_cents=10000,
            notes={"reason": "customer_request"},
        )

    fake_payment_resource.refund.assert_called_once_with(
        "pay_abc", {"amount": 10000, "notes": {"reason": "customer_request"}}
    )
    assert isinstance(result, RefundResult)
    assert result.provider_refund_id == "rfnd_abc"
    assert result.status == "processed"


# ---------------------------------------------------------------------------
# Stripe provider
# ---------------------------------------------------------------------------


def test_stripe_provider_verify_payment_signature_passthrough() -> None:
    """Documented no-op — Stripe's redirect carries its own signed session id.

    The webhook is the auth boundary for Stripe; this method exists to keep
    the abstract base contract uniform.
    """
    provider = StripeProvider()
    assert (
        provider.verify_payment_signature(
            provider_order_id="pi_anything",
            provider_payment_id="pi_anything",
            signature="ignored",
        )
        is True
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_get_provider_factory_returns_concrete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory returns the real provider when credentials are set, falls back
    to ``MockProvider`` in non-prod when they're missing, and raises for
    unknown providers.
    """
    from app.core.config import settings
    from app.services.payment_providers.mock_provider import MockProvider

    # 1) With credentials configured → real Razorpay/Stripe providers.
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_xxx", raising=False)
    monkeypatch.setattr(
        settings, "razorpay_key_secret", "secret_xxx", raising=False
    )
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_xxx", raising=False)
    monkeypatch.setattr(settings, "environment", "development", raising=False)
    assert isinstance(get_provider("razorpay"), RazorpayProvider)
    assert isinstance(get_provider("stripe"), StripeProvider)
    assert isinstance(
        get_provider("RAZORPAY"), RazorpayProvider
    )  # case-insensitive

    # 2) Without credentials in non-prod → MockProvider fallback.
    monkeypatch.setattr(settings, "razorpay_key_id", "", raising=False)
    monkeypatch.setattr(settings, "razorpay_key_secret", "", raising=False)
    monkeypatch.setattr(settings, "stripe_secret_key", "", raising=False)
    assert isinstance(get_provider("razorpay"), MockProvider)
    assert isinstance(get_provider("stripe"), MockProvider)

    # 3) Explicit "mock" works in non-prod.
    assert isinstance(get_provider("mock"), MockProvider)

    # 4) Unknown providers still raise.
    with pytest.raises(ValueError, match="Unknown payment provider"):
        get_provider("paypal")
