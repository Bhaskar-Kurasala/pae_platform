"""Provider webhook routes — Razorpay + Stripe.

Webhook etiquette: we ALWAYS return 200 OK except when the signature header is
entirely missing (which is misconfiguration, not transient — returning 400
forces an integrator to fix the dashboard rather than retry forever).

Pipeline (identical for both providers):

1. Read the raw body once — re-reading after FastAPI parses isn't safe.
2. Idempotently INSERT into ``payment_webhook_events`` keyed on
   ``(provider, provider_event_id)``. Duplicates short-circuit.
3. If the recorded row's ``signature_valid`` is False, log + ack 200.
4. Re-parse the envelope via the provider adapter (cheap, deterministic).
5. Dispatch with injected callables — order_resolver, attempt_recorder,
   entitlement_grant_fn, refund_handler. Any exception inside dispatch is
   caught + logged but never propagates as 5xx.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.order import (
    ORDER_STATUS_FULFILLED,
    ORDER_STATUS_PAID,
    Order,
)
from app.models.payment_attempt import (
    ATTEMPT_STATUS_CAPTURED,
    ATTEMPT_STATUS_FAILED,
    PaymentAttempt,
)
from app.models.refund import (
    REFUND_STATUS_PROCESSED,
    Refund,
)
from app.schemas.payments_v2 import WebhookAck
from app.services import entitlement_service, payment_webhook_event_service
from app.services.payment_providers import get_provider

log = structlog.get_logger()

router = APIRouter(prefix="/payments/webhook", tags=["payments-webhook"])


# ---------------------------------------------------------------------------
# Injectable collaborators (all async, all kwargs-only — see dispatch_event)
# ---------------------------------------------------------------------------


async def _order_resolver(
    db: AsyncSession,
    *,
    provider: str,
    provider_order_id: str | None,
) -> Order | None:
    if not provider_order_id:
        return None
    stmt = select(Order).where(
        Order.provider == provider,
        Order.provider_order_id == provider_order_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _attempt_recorder(
    db: AsyncSession,
    *,
    order: Order,
    provider_payment_id: str | None,
    entitlement_grant_fn: Any = None,
    failed: bool = False,
) -> None:
    """Insert a payment_attempt row + advance the order's state machine."""
    if failed:
        attempt = PaymentAttempt(
            order_id=order.id,
            provider=order.provider,
            provider_payment_id=provider_payment_id,
            amount_cents=order.amount_cents,
            status=ATTEMPT_STATUS_FAILED,
        )
        db.add(attempt)
        order.failure_reason = "webhook:payment_failed"
        await db.flush()
        return

    # Success path — short-circuit if already fulfilled.
    if order.status in (ORDER_STATUS_PAID, ORDER_STATUS_FULFILLED):
        log.info(
            "webhook.attempt_recorder.idempotent",
            order_id=str(order.id),
            status=order.status,
        )
        return

    attempt = PaymentAttempt(
        order_id=order.id,
        provider=order.provider,
        provider_payment_id=provider_payment_id,
        amount_cents=order.amount_cents,
        status=ATTEMPT_STATUS_CAPTURED,
    )
    db.add(attempt)

    now = datetime.now(UTC)
    order.status = ORDER_STATUS_PAID
    order.paid_at = now
    await db.flush()

    if entitlement_grant_fn is not None:
        await entitlement_grant_fn(db, order=order)
    else:
        await entitlement_service.grant_for_order(db, order=order)

    order.status = ORDER_STATUS_FULFILLED
    order.fulfilled_at = datetime.now(UTC)
    await db.flush()


async def _refund_handler(
    db: AsyncSession,
    envelope: Any,
) -> None:
    """Locate the related order, persist a Refund row, revoke entitlements."""
    related_order_id = envelope.related_provider_order_id
    related_payment_id = envelope.related_provider_payment_id
    provider_name = (
        envelope.raw_payload.get("payload", {})  # razorpay nesting
        .get("refund", {})
        .get("entity", {})
        .get("acquirer_data", {})
        .get("provider")
        if isinstance(envelope.raw_payload, dict)
        else None
    )

    order: Order | None = None
    if related_order_id:
        stmt = select(Order).where(
            Order.provider_order_id == related_order_id
        )
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()

    if order is None and related_payment_id:
        # Walk back via the payment_attempt → order chain.
        stmt2 = select(PaymentAttempt).where(
            PaymentAttempt.provider_payment_id == related_payment_id
        )
        result2 = await db.execute(stmt2)
        attempt = result2.scalar_one_or_none()
        if attempt is not None:
            order = await db.get(Order, attempt.order_id)

    if order is None:
        log.warning(
            "webhook.refund.order_not_found",
            related_order_id=related_order_id,
            related_payment_id=related_payment_id,
        )
        return

    refund_entity: dict[str, Any] = {}
    if isinstance(envelope.raw_payload, dict):
        refund_entity = (
            envelope.raw_payload.get("payload", {})
            .get("refund", {})
            .get("entity", {})
            or {}
        )

    provider_refund_id = str(refund_entity.get("id") or "") or None
    refund_amount = int(refund_entity.get("amount") or order.amount_cents)

    refund = Refund(
        order_id=order.id,
        provider=order.provider,
        provider_refund_id=provider_refund_id,
        amount_cents=refund_amount,
        currency=order.currency,
        status=REFUND_STATUS_PROCESSED,
        raw_response=refund_entity,
        processed_at=datetime.now(UTC),
    )
    db.add(refund)
    await db.flush()

    revoked = await entitlement_service.revoke_for_order(
        db, order_id=order.id
    )
    log.info(
        "webhook.refund.processed",
        order_id=str(order.id),
        revoked=revoked,
        provider=provider_name,
    )


# ---------------------------------------------------------------------------
# Shared handler
# ---------------------------------------------------------------------------


async def _handle_webhook(
    *,
    provider_name: str,
    request: Request,
    signature: str | None,
    db: AsyncSession,
) -> WebhookAck:
    if signature is None or signature == "":
        # Misconfiguration — Stripe/Razorpay both ALWAYS send a signature.
        # 400 forces the integrator to fix the dashboard rather than retry.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing signature header",
        )

    raw_body = await request.body()

    event, is_duplicate = (
        await payment_webhook_event_service.record_webhook_event(
            db,
            provider=provider_name,
            raw_body=raw_body,
            signature=signature,
        )
    )

    if is_duplicate:
        return WebhookAck(
            received=True, duplicate=True, event_type=event.event_type
        )

    if not event.signature_valid:
        log.warning(
            "webhook.invalid_signature",
            provider=provider_name,
            event_id=str(event.id),
            event_type=event.event_type,
        )
        return WebhookAck(
            received=True, duplicate=False, event_type=event.event_type
        )

    # Re-parse the envelope (cheap; deterministic) so we can route.
    related_order_id: uuid.UUID | None = None
    try:
        provider_client = get_provider(provider_name)
        envelope = provider_client.parse_webhook_event(raw_body=raw_body)

        await payment_webhook_event_service.dispatch_event(
            db,
            event=event,
            envelope=envelope,
            order_resolver=_order_resolver,
            attempt_recorder=_attempt_recorder,
            entitlement_grant_fn=entitlement_service.grant_for_order,
            refund_handler=_refund_handler,
        )

        # Best-effort: stamp related_order_id for forensics.
        if envelope.related_provider_order_id:
            order = await _order_resolver(
                db,
                provider=provider_name,
                provider_order_id=envelope.related_provider_order_id,
            )
            if order is not None:
                related_order_id = order.id

        await db.commit()
        await payment_webhook_event_service.mark_event_processed(
            db, event_id=event.id, related_order_id=related_order_id
        )
    except Exception as exc:
        # Webhook etiquette: never 5xx. Log + record the error on the ledger.
        log.exception(
            "webhook.dispatch.error",
            provider=provider_name,
            event_id=str(event.id),
            error=str(exc),
        )
        with contextlib.suppress(Exception):
            await db.rollback()
        with contextlib.suppress(Exception):
            await payment_webhook_event_service.mark_event_processed(
                db, event_id=event.id, error=str(exc)[:512]
            )

    return WebhookAck(
        received=True, duplicate=False, event_type=event.event_type
    )


# ---------------------------------------------------------------------------
# POST /payments/webhook/razorpay
# ---------------------------------------------------------------------------


@router.post("/razorpay", response_model=WebhookAck)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(
        default=None, alias="x-razorpay-signature"
    ),
    db: AsyncSession = Depends(get_db),
) -> WebhookAck:
    return await _handle_webhook(
        provider_name="razorpay",
        request=request,
        signature=x_razorpay_signature,
        db=db,
    )


# ---------------------------------------------------------------------------
# POST /payments/webhook/stripe
# ---------------------------------------------------------------------------


@router.post("/stripe", response_model=WebhookAck)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(
        default=None, alias="stripe-signature"
    ),
    db: AsyncSession = Depends(get_db),
) -> WebhookAck:
    return await _handle_webhook(
        provider_name="stripe",
        request=request,
        signature=stripe_signature,
        db=db,
    )
