"""Payment-webhook idempotency + dispatch service.

Every incoming provider webhook flows through here BEFORE any business logic
runs. The service:

1. Verifies the signature (the row is recorded either way for audit).
2. Parses the envelope via the provider adapter.
3. Tries to INSERT a row into ``payment_webhook_events``. The
   ``(provider, provider_event_id)`` UNIQUE constraint is the dedup boundary —
   a duplicate raises ``IntegrityError`` and we short-circuit cleanly with
   ``is_duplicate=True``.
4. Returns ``(row, is_duplicate)`` so the route can decide whether to dispatch.

The dispatch step itself is fully dependency-injected — every external call
(order resolver, attempt recorder, entitlement grant, refund handler) is
passed in by the caller. This lets us unit-test routing without rebuilding
the whole stack.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_webhook_event import PaymentWebhookEvent

# The provider package is owned by a parallel agent — we import the public
# surface here. Tests patch ``get_provider`` on this module to inject a
# synthetic provider so we never touch real provider SDKs in unit tests.
from app.services.payment_providers import (  # noqa: E402
    WebhookEventEnvelope,
    get_provider,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Event-type constants (provider-agnostic surface)
# ---------------------------------------------------------------------------

# Razorpay
RAZORPAY_PAYMENT_CAPTURED = "payment.captured"
RAZORPAY_PAYMENT_FAILED = "payment.failed"
RAZORPAY_REFUND_PROCESSED = "refund.processed"
RAZORPAY_REFUND_CREATED = "refund.created"

# Stripe
STRIPE_CHECKOUT_COMPLETED = "checkout.session.completed"
STRIPE_PAYMENT_INTENT_SUCCEEDED = "payment_intent.succeeded"

PAYMENT_SUCCESS_EVENTS = {
    RAZORPAY_PAYMENT_CAPTURED,
    STRIPE_CHECKOUT_COMPLETED,
    STRIPE_PAYMENT_INTENT_SUCCEEDED,
}
PAYMENT_FAILURE_EVENTS = {RAZORPAY_PAYMENT_FAILED}
REFUND_EVENTS = {RAZORPAY_REFUND_PROCESSED, RAZORPAY_REFUND_CREATED}


# ---------------------------------------------------------------------------
# Idempotent insert
# ---------------------------------------------------------------------------


async def record_webhook_event(
    db: AsyncSession,
    *,
    provider: str,
    raw_body: bytes,
    signature: str | None,
) -> tuple[PaymentWebhookEvent, bool]:
    """Idempotently record an incoming webhook event.

    Returns ``(event_row, is_duplicate)``. When ``is_duplicate=True`` the
    caller MUST NOT re-dispatch business logic — the original handler
    already did (or is racing to do) the work.

    Invalid signatures are recorded too (with ``signature_valid=False`` and
    ``error="invalid_signature"``) so we have an audit trail of attempted
    forgeries; the caller is responsible for not dispatching when the
    returned row's ``signature_valid`` is False.
    """
    provider_client = get_provider(provider)

    signature_valid = bool(
        signature
        and provider_client.verify_webhook_signature(
            raw_body=raw_body, signature=signature
        )
    )

    envelope: WebhookEventEnvelope = provider_client.parse_webhook_event(
        raw_body=raw_body
    )

    event = PaymentWebhookEvent(
        provider=provider,
        provider_event_id=envelope.provider_event_id,
        event_type=envelope.event_type,
        raw_body=raw_body,
        signature=signature,
        signature_valid=signature_valid,
        error=None if signature_valid else "invalid_signature",
    )
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing_stmt = select(PaymentWebhookEvent).where(
            PaymentWebhookEvent.provider == provider,
            PaymentWebhookEvent.provider_event_id == envelope.provider_event_id,
        )
        result = await db.execute(existing_stmt)
        existing = result.scalar_one()
        log.info(
            "webhook.duplicate",
            provider=provider,
            provider_event_id=envelope.provider_event_id,
            existing_event_id=str(existing.id),
        )
        return existing, True

    await db.refresh(event)

    log.info(
        "webhook.recorded",
        provider=provider,
        provider_event_id=envelope.provider_event_id,
        event_type=envelope.event_type,
        signature_valid=signature_valid,
        event_id=str(event.id),
    )
    return event, False


async def mark_event_processed(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    related_order_id: uuid.UUID | None = None,
    error: str | None = None,
) -> PaymentWebhookEvent | None:
    """Stamp an event as processed (success or failure).

    ``error`` is set only when dispatch raised; on the happy path it stays
    ``None`` and ``processed_at`` records the success.
    """
    event = await db.get(PaymentWebhookEvent, event_id)
    if event is None:
        return None

    event.processed_at = datetime.now(UTC)
    if related_order_id is not None:
        event.related_order_id = related_order_id
    if error is not None:
        event.error = error

    await db.commit()
    await db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# Dispatch — pure DI, no service-layer cycles
# ---------------------------------------------------------------------------


async def dispatch_event(
    db: AsyncSession,
    *,
    event: PaymentWebhookEvent,
    envelope: WebhookEventEnvelope,
    order_resolver: Callable[..., Awaitable[Any]] | None = None,
    attempt_recorder: Callable[..., Awaitable[Any]] | None = None,
    entitlement_grant_fn: Callable[..., Awaitable[Any]] | None = None,
    refund_handler: Callable[..., Awaitable[Any]] | None = None,
) -> str:
    """Route a verified envelope to the right handler.

    All side-effecting collaborators are injected so the routing logic itself
    is trivially unit-testable. Returns the routing decision name (for logs +
    test assertions): ``"payment_success"``, ``"payment_failed"``,
    ``"refund"``, or ``"unhandled"``.
    """
    event_type = event.event_type

    if event_type in PAYMENT_SUCCESS_EVENTS:
        if order_resolver is None:
            log.warning(
                "webhook.dispatch.missing_order_resolver",
                event_type=event_type,
                event_id=str(event.id),
            )
            return "unhandled"

        order = await order_resolver(
            db,
            provider=event.provider,
            provider_order_id=envelope.related_provider_order_id,
        )
        if order is None:
            log.warning(
                "webhook.dispatch.order_not_found",
                event_type=event_type,
                provider_order_id=envelope.related_provider_order_id,
            )
            return "unhandled"

        if attempt_recorder is None:
            raise ValueError(
                "attempt_recorder required for payment-success events"
            )

        await attempt_recorder(
            db,
            order=order,
            provider_payment_id=envelope.related_provider_payment_id,
            entitlement_grant_fn=entitlement_grant_fn,
        )
        log.info(
            "webhook.dispatch.payment_success",
            event_id=str(event.id),
            order_id=str(order.id),
        )
        return "payment_success"

    if event_type in PAYMENT_FAILURE_EVENTS:
        if order_resolver is None:
            log.warning(
                "webhook.dispatch.missing_order_resolver",
                event_type=event_type,
            )
            return "unhandled"

        order = await order_resolver(
            db,
            provider=event.provider,
            provider_order_id=envelope.related_provider_order_id,
        )
        if order is None:
            log.warning(
                "webhook.dispatch.order_not_found",
                event_type=event_type,
            )
            return "unhandled"

        # The route owns mark_order_failed via attempt_recorder convention —
        # we keep the routing layer dumb and let the caller decide what
        # "failed" means (refund the auth hold? notify the user? both?).
        if attempt_recorder is None:
            log.warning(
                "webhook.dispatch.payment_failed.no_recorder",
                event_id=str(event.id),
            )
            return "unhandled"

        await attempt_recorder(
            db,
            order=order,
            provider_payment_id=envelope.related_provider_payment_id,
            failed=True,
        )
        log.info(
            "webhook.dispatch.payment_failed",
            event_id=str(event.id),
            order_id=str(order.id),
        )
        return "payment_failed"

    if event_type in REFUND_EVENTS:
        if refund_handler is None:
            log.warning(
                "webhook.dispatch.refund.no_handler",
                event_id=str(event.id),
            )
            return "unhandled"
        await refund_handler(db, envelope)
        log.info(
            "webhook.dispatch.refund",
            event_id=str(event.id),
            event_type=event_type,
        )
        return "refund"

    log.info(
        "webhook.unhandled_event",
        event_id=str(event.id),
        event_type=event_type,
        provider=event.provider,
    )
    return "unhandled"
