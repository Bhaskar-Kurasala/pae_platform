"""Order service — create / get / list / confirm orders.

This module owns the local lifecycle of an :class:`Order` row plus its
associated :class:`PaymentAttempt` rows. Provider-specific logic (Razorpay,
Stripe) lives behind the
``app.services.payment_providers`` factory and is dependency-injected into the
service so tests can mock it without touching the SDKs.

The ``confirm_order`` flow is intentionally idempotent: callers can replay the
same ``(order_id, provider_payment_id, signature)`` tuple (e.g. from a stuck
webhook + a checkout-success redirect arriving in either order) and only one
``PaymentAttempt`` + one entitlement-grant will be performed.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.course_bundle import CourseBundle
from app.models.order import (
    ORDER_STATUS_CREATED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_FULFILLED,
    ORDER_STATUS_PAID,
    TARGET_BUNDLE,
    TARGET_COURSE,
    Order,
)
from app.models.payment_attempt import (
    ATTEMPT_STATUS_CAPTURED,
    ATTEMPT_STATUS_FAILED,
    PaymentAttempt,
)
from app.models.user import User

# The provider package is owned by a parallel agent — we import the public
# surface here. Tests patch ``app.services.order_service.get_provider`` to
# inject a synthetic provider so we don't need real Razorpay/Stripe SDKs.
from app.services.payment_providers import (  # noqa: E402
    SignatureMismatchError,
    get_provider,
)

# Type alias for the entitlement-grant callable — keeps the signature pinned
# so tests pass an ``AsyncMock`` with the same kwargs the real service uses.
EntitlementGrantFn = Callable[..., Awaitable[Any]]

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def generate_receipt_number(
    order_id: uuid.UUID, *, now: datetime | None = None
) -> str:
    """Build a deterministic receipt number of the form ``CF-YYYYMMDD-XXXXXX``.

    The date prefix gives finance a quick visual sort; the 6-char hex suffix
    (first 6 chars of the order UUID) is collision-resistant in practice for
    the volume we handle (~1e6 orders before birthday-paradox starts to bite).
    """
    when = now or datetime.now(UTC)
    suffix = uuid.UUID(str(order_id)).hex[:6].upper()
    return f"CF-{when.strftime('%Y%m%d')}-{suffix}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_target_amount(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: uuid.UUID,
) -> tuple[int, str]:
    """Look up the price of the target SKU.

    Returns ``(amount_cents, currency)``. Raises ``HTTPException`` if the
    target is missing, unpublished, or zero-priced (free items go through the
    free-enroll route, NOT through orders).
    """
    if target_type == TARGET_COURSE:
        course = await db.get(Course, target_id)
        if course is None or not course.is_published:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course not found or not published",
            )
        amount = int(course.price_cents or 0)
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Free courses must use the free-enroll flow, "
                    "not order_service.create_order"
                ),
            )
        # Courses don't carry a currency column today — default to INR which
        # matches every other paid SKU. The order itself stores the currency
        # so future per-course currency overrides won't require a backfill.
        return amount, "INR"

    if target_type == TARGET_BUNDLE:
        bundle = await db.get(CourseBundle, target_id)
        if bundle is None or not bundle.is_published:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bundle not found or not published",
            )
        amount = int(bundle.price_cents or 0)
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bundle has no price — cannot create paid order",
            )
        return amount, bundle.currency or "INR"

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported target_type: {target_type!r}",
    )


async def _default_entitlement_grant(
    db: AsyncSession, *, order: Order
) -> Any:
    """Default entitlement-grant — looks up the parallel-built service lazily.

    Tests inject their own callable via ``entitlement_grant_fn`` and never
    hit this branch; production callers fall through here so they get the
    real implementation without an explicit wiring step.
    """
    from app.services import entitlement_service  # type: ignore[attr-defined]

    return await entitlement_service.grant_for_order(db, order=order)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_order(
    db: AsyncSession,
    *,
    user: User,
    target_type: Literal["course", "bundle"],
    target_id: uuid.UUID,
    provider: str,
    currency: str | None = None,
) -> Order:
    """Create a local Order + a matching provider order; return the persisted row."""
    amount_cents, target_currency = await _resolve_target_amount(
        db, target_type=target_type, target_id=target_id
    )
    final_currency = currency or target_currency

    order = Order(
        user_id=user.id,
        target_type=target_type,
        target_id=target_id,
        amount_cents=amount_cents,
        currency=final_currency,
        provider=provider,
        status=ORDER_STATUS_CREATED,
        metadata_={},
    )
    db.add(order)
    await db.flush()  # populate order.id so we can mint a receipt + provider id

    receipt_number = generate_receipt_number(order.id)
    order.receipt_number = receipt_number

    provider_client = get_provider(provider)
    provider_order = await provider_client.create_order(
        amount_cents=amount_cents,
        currency=final_currency,
        receipt=receipt_number,
        notes={
            "user_id": str(user.id),
            "target_type": target_type,
            "target_id": str(target_id),
        },
    )
    order.provider_order_id = provider_order.provider_order_id

    await db.commit()
    await db.refresh(order)

    log.info(
        "order.created",
        order_id=str(order.id),
        user_id=str(user.id),
        target_type=target_type,
        target_id=str(target_id),
        amount_cents=amount_cents,
        provider=provider,
        provider_order_id=order.provider_order_id,
    )
    return order


async def get_order_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    order_id: uuid.UUID,
) -> Order | None:
    """Fetch one order, scoped to its owning user (own-only access)."""
    stmt = select(Order).where(
        Order.id == order_id,
        Order.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_orders_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 50,
) -> list[Order]:
    """Return the user's orders, newest first."""
    stmt = (
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(desc(Order.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def confirm_order(
    db: AsyncSession,
    *,
    user: User,
    order_id: uuid.UUID,
    provider_payment_id: str,
    signature: str,
    entitlement_grant_fn: EntitlementGrantFn | None = None,
) -> Order:
    """Verify a checkout signature and fulfill the order.

    Idempotent: if the order is already paid/fulfilled, returns the row as-is
    without creating a second :class:`PaymentAttempt` or re-granting entitlements.
    """
    order = await get_order_for_user(
        db, user_id=user.id, order_id=order_id
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # Idempotent short-circuit — anything past 'paid' is already done.
    if order.status in (ORDER_STATUS_PAID, ORDER_STATUS_FULFILLED):
        log.info(
            "order.confirm.idempotent_short_circuit",
            order_id=str(order.id),
            status=order.status,
        )
        return order

    if not order.provider_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order has no provider_order_id — cannot verify signature",
        )

    provider_client = get_provider(order.provider)
    is_valid = provider_client.verify_payment_signature(
        provider_order_id=order.provider_order_id,
        provider_payment_id=provider_payment_id,
        signature=signature,
    )
    if not is_valid:
        log.warning(
            "order.confirm.bad_signature",
            order_id=str(order.id),
            provider=order.provider,
        )
        raise SignatureMismatchError(
            f"Signature mismatch for order {order.id}"
        )

    attempt = PaymentAttempt(
        order_id=order.id,
        provider=order.provider,
        provider_payment_id=provider_payment_id,
        provider_signature=signature,
        amount_cents=order.amount_cents,
        status=ATTEMPT_STATUS_CAPTURED,
    )
    db.add(attempt)

    now = datetime.now(UTC)
    order.status = ORDER_STATUS_PAID
    order.paid_at = now
    await db.flush()

    grant_fn = entitlement_grant_fn or _default_entitlement_grant
    await grant_fn(db, order=order)

    order.status = ORDER_STATUS_FULFILLED
    order.fulfilled_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(order)

    log.info(
        "order.confirmed",
        order_id=str(order.id),
        user_id=str(user.id),
        provider_payment_id=provider_payment_id,
    )
    return order


async def mark_order_failed(
    db: AsyncSession,
    *,
    order_id: uuid.UUID,
    reason: str,
) -> Order | None:
    """Mark an order failed and (best-effort) the latest attempt failed too."""
    order = await db.get(Order, order_id)
    if order is None:
        return None

    order.status = ORDER_STATUS_FAILED
    order.failure_reason = reason

    latest_attempt_stmt = (
        select(PaymentAttempt)
        .where(PaymentAttempt.order_id == order_id)
        .order_by(desc(PaymentAttempt.attempted_at))
        .limit(1)
    )
    result = await db.execute(latest_attempt_stmt)
    latest_attempt = result.scalar_one_or_none()
    if latest_attempt is not None:
        latest_attempt.status = ATTEMPT_STATUS_FAILED
        latest_attempt.failure_reason = reason

    await db.commit()
    await db.refresh(order)

    log.warning(
        "order.failed",
        order_id=str(order.id),
        reason=reason,
    )
    return order
