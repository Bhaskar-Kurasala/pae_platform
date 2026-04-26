"""Unit tests for ``app.services.payment_webhook_event_service``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models.payment_webhook_event import PaymentWebhookEvent
from app.services import payment_webhook_event_service as wh_svc
from app.services.payment_webhook_event_service import (
    WebhookEventEnvelope,
    dispatch_event,
    record_webhook_event,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    *,
    provider_event_id: str = "evt_abc123",
    event_type: str = "payment.captured",
    related_order: str | None = "order_rzp_abc",
    related_payment: str | None = "pay_rzp_xyz",
) -> WebhookEventEnvelope:
    return WebhookEventEnvelope(
        provider_event_id=provider_event_id,
        event_type=event_type,
        related_provider_order_id=related_order,
        related_provider_payment_id=related_payment,
        raw_payload={"foo": "bar"},
    )


def _provider_mock(
    *,
    envelope: WebhookEventEnvelope | None = None,
    signature_valid: bool = True,
) -> MagicMock:
    provider = MagicMock()
    provider.verify_webhook_signature = MagicMock(return_value=signature_valid)
    provider.parse_webhook_event = MagicMock(
        return_value=envelope or _make_envelope()
    )
    return provider


# ---------------------------------------------------------------------------
# record_webhook_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_webhook_event_inserts_with_signature_valid(
    db_session, monkeypatch
) -> None:
    provider = _provider_mock(signature_valid=True)
    monkeypatch.setattr(wh_svc, "get_provider", lambda name: provider)

    event, is_dup = await record_webhook_event(
        db_session,
        provider="razorpay",
        raw_body=b'{"event":"payment.captured"}',
        signature="sig_valid",
    )

    assert is_dup is False
    assert event.id is not None
    assert event.provider == "razorpay"
    assert event.provider_event_id == "evt_abc123"
    assert event.event_type == "payment.captured"
    assert event.signature_valid is True
    assert event.signature == "sig_valid"
    assert event.error is None


@pytest.mark.asyncio
async def test_record_webhook_event_returns_duplicate_on_repeat(
    db_session, monkeypatch
) -> None:
    provider = _provider_mock(signature_valid=True)
    monkeypatch.setattr(wh_svc, "get_provider", lambda name: provider)

    first, dup1 = await record_webhook_event(
        db_session,
        provider="razorpay",
        raw_body=b"{}",
        signature="sig_valid",
    )
    assert dup1 is False

    second, dup2 = await record_webhook_event(
        db_session,
        provider="razorpay",
        raw_body=b"{}",
        signature="sig_valid",
    )
    assert dup2 is True
    assert second.id == first.id

    rows = (
        await db_session.execute(
            select(PaymentWebhookEvent).where(
                PaymentWebhookEvent.provider == "razorpay",
                PaymentWebhookEvent.provider_event_id == "evt_abc123",
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_record_webhook_event_records_invalid_signature_but_returns_duplicate_false(
    db_session, monkeypatch
) -> None:
    provider = _provider_mock(signature_valid=False)
    monkeypatch.setattr(wh_svc, "get_provider", lambda name: provider)

    event, is_dup = await record_webhook_event(
        db_session,
        provider="razorpay",
        raw_body=b'{"event":"payment.captured"}',
        signature="sig_bad",
    )

    assert is_dup is False
    assert event.signature_valid is False
    assert event.error == "invalid_signature"


# ---------------------------------------------------------------------------
# dispatch_event
# ---------------------------------------------------------------------------


def _row_for(
    *, event_type: str = "payment.captured", provider: str = "razorpay"
) -> PaymentWebhookEvent:
    """Build an unsaved PaymentWebhookEvent row for routing assertions."""
    import uuid as _uuid

    return PaymentWebhookEvent(
        id=_uuid.uuid4(),
        provider=provider,
        provider_event_id="evt_abc",
        event_type=event_type,
        raw_body=b"{}",
        signature="sig",
        signature_valid=True,
    )


@pytest.mark.asyncio
async def test_dispatch_event_routes_payment_captured_to_confirm(
    db_session,
) -> None:
    event = _row_for(event_type="payment.captured")
    envelope = _make_envelope(event_type="payment.captured")

    fake_order = MagicMock()
    fake_order.id = "order-uuid-1"
    order_resolver = AsyncMock(return_value=fake_order)
    attempt_recorder = AsyncMock()
    grant_fn = AsyncMock()

    decision = await dispatch_event(
        db_session,
        event=event,
        envelope=envelope,
        order_resolver=order_resolver,
        attempt_recorder=attempt_recorder,
        entitlement_grant_fn=grant_fn,
    )

    assert decision == "payment_success"
    order_resolver.assert_awaited_once()
    _, resolver_kwargs = order_resolver.call_args
    assert resolver_kwargs["provider"] == "razorpay"
    assert resolver_kwargs["provider_order_id"] == "order_rzp_abc"

    attempt_recorder.assert_awaited_once()
    _, rec_kwargs = attempt_recorder.call_args
    assert rec_kwargs["order"] is fake_order
    assert rec_kwargs["provider_payment_id"] == "pay_rzp_xyz"
    assert rec_kwargs["entitlement_grant_fn"] is grant_fn


@pytest.mark.asyncio
async def test_dispatch_event_routes_refund_processed_to_handler(
    db_session,
) -> None:
    event = _row_for(event_type="refund.processed")
    envelope = _make_envelope(
        event_type="refund.processed", related_order=None, related_payment=None
    )

    refund_handler = AsyncMock()

    decision = await dispatch_event(
        db_session,
        event=event,
        envelope=envelope,
        refund_handler=refund_handler,
    )

    assert decision == "refund"
    refund_handler.assert_awaited_once()
    args, _ = refund_handler.call_args
    # signature: refund_handler(db, envelope)
    assert args[0] is db_session
    assert args[1] is envelope


@pytest.mark.asyncio
async def test_dispatch_event_logs_unhandled_event(
    db_session, capsys
) -> None:
    event = _row_for(event_type="some.weird.event")
    envelope = _make_envelope(event_type="some.weird.event")

    decision = await dispatch_event(
        db_session,
        event=event,
        envelope=envelope,
    )

    assert decision == "unhandled"
    # structlog renders to stdout in test envs (not stdlib logging) so
    # capsys is the right capture surface — caplog stays empty.
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert "unhandled_event" in blob or "some.weird.event" in blob
