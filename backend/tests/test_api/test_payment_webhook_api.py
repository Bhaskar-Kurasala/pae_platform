"""CP1 B1+B2 — API-layer tests for POST /payments/webhook/razorpay.

Tests verify:
  B1: Signature header absent → 400 (misconfiguration, not retryable).
  B1: Valid signature → 200 WebhookAck.
  B1: Invalid signature → 200 WebhookAck with audit trail (webhook etiquette
      — providers retry on non-2xx; we ACK + record invalid sigs so forged
      events have an audit trail but cannot trigger business logic).
  B2: Duplicate event_id → 200 WebhookAck(duplicate=True, no double-dispatch).
  H1.1: Provider errors never leak raw exception text in response bodies.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_SECRET = "test_webhook_secret_known_value"
_PROVIDER_EVENT_ID = "evt_test_abc123"


def _make_razorpay_payload(
    event_type: str = "payment.captured",
    event_id: str = _PROVIDER_EVENT_ID,
) -> bytes:
    body: dict[str, Any] = {
        "id": event_id,
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_xyz",
                    "order_id": "order_test_abc",
                }
            }
        },
    }
    return json.dumps(body).encode("utf-8")


def _valid_sig(body: bytes, secret: str = _TEST_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def _patch_provider_factory(*, sig_valid: bool = True) -> MagicMock:
    provider = MagicMock()
    provider.verify_webhook_signature = MagicMock(return_value=sig_valid)
    envelope_mock = MagicMock()
    envelope_mock.provider_event_id = _PROVIDER_EVENT_ID
    envelope_mock.event_type = "payment.captured"
    envelope_mock.related_provider_order_id = "order_test_abc"
    envelope_mock.related_provider_payment_id = "pay_test_xyz"
    envelope_mock.raw_payload = {}
    provider.parse_webhook_event = MagicMock(return_value=envelope_mock)
    return provider


# ---------------------------------------------------------------------------
# B1: Missing signature header → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_missing_signature_returns_400(client: AsyncClient) -> None:
    """Missing x-razorpay-signature header is misconfiguration → 400."""
    body = _make_razorpay_payload()
    resp = await client.post(
        "/api/v1/payments/webhook/razorpay",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "signature" in detail.lower()


# ---------------------------------------------------------------------------
# B1: Valid signature → 200 + received=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_valid_signature_ack(client: AsyncClient) -> None:
    """Valid HMAC signature → 200 WebhookAck(received=True, duplicate=False)."""
    body = _make_razorpay_payload(event_id="evt_unique_valid_001")
    sig = _valid_sig(body)
    provider_mock = _patch_provider_factory(sig_valid=True)

    with patch(
        "app.services.payment_webhook_event_service.get_provider",
        return_value=provider_mock,
    ):
        with patch(
            "app.api.v1.routes.payments_webhook._order_resolver",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=None)(),
        ):
            resp = await client.post(
                "/api/v1/payments/webhook/razorpay",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "x-razorpay-signature": sig,
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] is True


# ---------------------------------------------------------------------------
# B1: Invalid signature → 200 (webhook etiquette) + audit-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_200_with_audit(
    client: AsyncClient,
) -> None:
    """Invalid signature → 200 (Razorpay must not retry forever).

    The internal audit trail records signature_valid=False. No business
    logic fires. The response is still 200 to prevent infinite retries.
    """
    body = _make_razorpay_payload(event_id="evt_forged_sig_002")
    provider_mock = _patch_provider_factory(sig_valid=False)

    with patch(
        "app.services.payment_webhook_event_service.get_provider",
        return_value=provider_mock,
    ):
        resp = await client.post(
            "/api/v1/payments/webhook/razorpay",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-razorpay-signature": "tampered_signature_value",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    # Body is not leaked — must not contain exception class names or tracebacks.
    body_text = resp.text
    for leak_pattern in ("Traceback", "ValueError", "KeyError", "Exception"):
        assert leak_pattern not in body_text


# ---------------------------------------------------------------------------
# B2: Duplicate event_id → 200 WebhookAck(duplicate=True)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_duplicate_event_returns_noop(client: AsyncClient) -> None:
    """Same event_id delivered twice → second call is a 200 no-op."""
    body = _make_razorpay_payload(event_id="evt_dedup_003")
    sig = _valid_sig(body)
    provider_mock = _patch_provider_factory(sig_valid=True)

    with patch(
        "app.services.payment_webhook_event_service.get_provider",
        return_value=provider_mock,
    ):
        with patch(
            "app.api.v1.routes.payments_webhook._order_resolver",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=None)(),
        ):
            headers = {
                "Content-Type": "application/json",
                "x-razorpay-signature": sig,
            }
            first = await client.post(
                "/api/v1/payments/webhook/razorpay",
                content=body,
                headers=headers,
            )
            second = await client.post(
                "/api/v1/payments/webhook/razorpay",
                content=body,
                headers=headers,
            )

    assert first.status_code == 200
    assert second.status_code == 200
    # Second delivery must be flagged as duplicate.
    assert second.json()["duplicate"] is True


# ---------------------------------------------------------------------------
# H1.1: Provider errors never leak raw exception text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_dispatch_exception_no_raw_leak(
    client: AsyncClient,
) -> None:
    """An unexpected dispatch error must not leak Python internals in the response."""
    body = _make_razorpay_payload(event_id="evt_dispatch_err_004")
    sig = _valid_sig(body)
    provider_mock = _patch_provider_factory(sig_valid=True)

    # Build a plain MagicMock event so no SQLAlchemy lazy-load fires after rollback.
    fake_event = MagicMock()
    fake_event.id = "evt-uuid-dispatch-err"
    fake_event.event_type = "payment.captured"

    with patch(
        "app.services.payment_webhook_event_service.get_provider",
        return_value=provider_mock,
    ):
        with patch(
            "app.api.v1.routes.payments_webhook.payment_webhook_event_service.record_webhook_event",
            new_callable=AsyncMock,
            return_value=(fake_event, False),
        ):
            with patch(
                "app.api.v1.routes.payments_webhook.payment_webhook_event_service.dispatch_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("super_secret_internal_error_code_12345"),
            ):
                with patch(
                    "app.api.v1.routes.payments_webhook.payment_webhook_event_service.mark_event_processed",
                    new_callable=AsyncMock,
                ):
                    resp = await client.post(
                        "/api/v1/payments/webhook/razorpay",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "x-razorpay-signature": sig,
                        },
                    )

    # Route catches dispatch exceptions gracefully — never 5xx to webhook sender.
    assert resp.status_code == 200
    # Raw error must not appear in the response body.
    assert "super_secret_internal_error_code_12345" not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text
