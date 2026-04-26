"""Payments v2 routes — order lifecycle + free enrollment + receipts.

Mounted at ``/api/v1/payments``. Provider-agnostic: the same endpoints serve
Razorpay today and Stripe later. Razorpay-specific fields (``razorpay_key_id``,
the ``razorpay_*`` confirm body) are nullable so the contract stays additive.

Routes here intentionally stay thin — they delegate to ``order_service`` and
``entitlement_service`` for all state transitions.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.course import Course
from app.models.course_bundle import CourseBundle
from app.models.order import Order
from app.models.payment_attempt import PaymentAttempt
from app.models.user import User
from app.schemas.payments_v2 import (
    ConfirmOrderRequest,
    ConfirmOrderResponse,
    CreateOrderRequest,
    CreateOrderResponse,
    FreeEnrollRequest,
    FreeEnrollResponse,
    OrderDetailResponse,
    OrderListItem,
    PaymentAttemptItem,
)
from app.services import entitlement_service, order_service
from app.services.payment_providers import (
    PaymentProviderError,
    ProviderUnavailableError,
    SignatureMismatchError,
)
from app.services.pdf_renderer import _render_fallback_pdf  # noqa: PLC2701

log = structlog.get_logger()

router = APIRouter(prefix="/payments", tags=["payments-v2"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_target_title(
    db: AsyncSession, *, target_type: str, target_id: uuid.UUID
) -> str | None:
    """Look up the human-readable title for a (target_type, target_id) pair.

    Returns None when the referenced row no longer exists — this happens for
    order rows whose target was hard-deleted; the order itself is preserved
    for finance audit so the route shouldn't 500 on the missing FK.
    """
    if target_type == "course":
        course = await db.get(Course, target_id)
        return course.title if course is not None else None
    if target_type == "bundle":
        bundle = await db.get(CourseBundle, target_id)
        return bundle.title if bundle is not None else None
    return None


async def _attempts_for_order(
    db: AsyncSession, *, order_id: uuid.UUID
) -> list[PaymentAttempt]:
    stmt = (
        select(PaymentAttempt)
        .where(PaymentAttempt.order_id == order_id)
        .order_by(desc(PaymentAttempt.attempted_at))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _razorpay_key_for(provider: str) -> str | None:
    """Return the public Razorpay key id when the provider is razorpay.

    The key id is intentionally NOT a secret — the frontend ships it to
    Razorpay's checkout JS verbatim. Returning ``None`` for other providers
    keeps the response shape stable across SKU types.
    """
    if provider == "razorpay" and settings.razorpay_key_id:
        return settings.razorpay_key_id
    return None


# ---------------------------------------------------------------------------
# POST /payments/orders
# ---------------------------------------------------------------------------


@router.post(
    "/orders",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_route(
    payload: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateOrderResponse:
    """Create an order on the provider, persist it, return the checkout payload."""
    try:
        order = await order_service.create_order(
            db,
            user=current_user,
            target_type=payload.target_type,
            target_id=payload.target_id,
            provider=payload.provider,
            currency=payload.currency or settings.payments_default_currency,
        )
    except ValueError as exc:
        # Domain-level rejection: unpublished course / zero amount / unknown
        # target. Surface as 400 so the client can show the user a message
        # rather than a 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderUnavailableError as exc:
        # Razorpay/Stripe is misconfigured or down — return 502 so the caller
        # can retry with backoff. Logged with full context already by the
        # provider service.
        log.warning(
            "payments.order.provider_unavailable",
            provider=payload.provider,
            user_id=str(current_user.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Payment provider unavailable: {exc}",
        ) from exc
    except PaymentProviderError as exc:
        log.error(
            "payments.order.provider_error",
            provider=payload.provider,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502, detail=str(exc)
        ) from exc

    target_title = (
        await _resolve_target_title(
            db, target_type=order.target_type, target_id=order.target_id
        )
        or "Order"
    )

    return CreateOrderResponse(
        order_id=order.id,
        provider=order.provider,
        provider_order_id=order.provider_order_id or "",
        amount_cents=order.amount_cents,
        currency=order.currency,
        receipt_number=order.receipt_number or "",
        razorpay_key_id=_razorpay_key_for(order.provider),
        user_email=current_user.email,
        user_name=current_user.full_name,
        target_title=target_title,
    )


# ---------------------------------------------------------------------------
# GET /payments/orders
# ---------------------------------------------------------------------------


@router.get("/orders", response_model=list[OrderListItem])
async def list_orders_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrderListItem]:
    rows = await order_service.list_orders_for_user(
        db, user_id=current_user.id
    )
    items: list[OrderListItem] = []
    for order in rows:
        title = await _resolve_target_title(
            db, target_type=order.target_type, target_id=order.target_id
        )
        items.append(
            OrderListItem(
                id=order.id,
                target_type=order.target_type,
                target_id=order.target_id,
                target_title=title,
                amount_cents=order.amount_cents,
                currency=order.currency,
                status=order.status,
                receipt_number=order.receipt_number,
                created_at=order.created_at,
            )
        )
    return items


# ---------------------------------------------------------------------------
# GET /payments/orders/{order_id}
# ---------------------------------------------------------------------------


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
async def get_order_route(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    order = await order_service.get_order_for_user(
        db, user_id=current_user.id, order_id=order_id
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    title = await _resolve_target_title(
        db, target_type=order.target_type, target_id=order.target_id
    )
    attempts = await _attempts_for_order(db, order_id=order.id)
    return OrderDetailResponse(
        id=order.id,
        target_type=order.target_type,
        target_id=order.target_id,
        target_title=title,
        amount_cents=order.amount_cents,
        currency=order.currency,
        status=order.status,
        receipt_number=order.receipt_number,
        created_at=order.created_at,
        paid_at=order.paid_at,
        fulfilled_at=order.fulfilled_at,
        failure_reason=order.failure_reason,
        payment_attempts=[
            PaymentAttemptItem.model_validate(a) for a in attempts
        ],
    )


# ---------------------------------------------------------------------------
# GET /payments/orders/{order_id}/receipt.pdf
# ---------------------------------------------------------------------------


@router.get("/orders/{order_id}/receipt.pdf")
async def get_order_receipt_pdf(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stream a basic text-based PDF receipt.

    Reuses ``pdf_renderer._render_fallback_pdf`` so we get the same parseable,
    no-deps PDF that the application_kit + tailored_resume routes fall back
    to. A future iteration can swap to a WeasyPrint-rendered HTML template
    without changing the route contract.
    """
    order = await order_service.get_order_for_user(
        db, user_id=current_user.id, order_id=order_id
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    title = (
        await _resolve_target_title(
            db, target_type=order.target_type, target_id=order.target_id
        )
        or "Order"
    )
    receipt_number = order.receipt_number or str(order.id)

    lines = [
        "PAYMENT RECEIPT",
        f"Receipt: {receipt_number}",
        f"Order ID: {order.id}",
        "",
        f"Customer: {current_user.full_name}",
        f"Email: {current_user.email}",
        "",
        "ITEM",
        f"{order.target_type.title()}: {title}",
        "",
        "AMOUNT",
        f"{order.amount_cents / 100:.2f} {order.currency}",
        "",
        f"Status: {order.status}",
        f"Paid at: {order.paid_at.isoformat() if order.paid_at else '—'}",
        f"Provider: {order.provider}",
    ]
    pdf_bytes = _render_fallback_pdf(lines)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="receipt-{receipt_number}.pdf"'
            ),
        },
    )


# ---------------------------------------------------------------------------
# POST /payments/orders/{order_id}/confirm
# ---------------------------------------------------------------------------


@router.post(
    "/orders/{order_id}/confirm", response_model=ConfirmOrderResponse
)
async def confirm_order_route(
    order_id: uuid.UUID,
    payload: ConfirmOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConfirmOrderResponse:
    """Verify the provider signature, capture the attempt, grant entitlements."""
    if not payload.razorpay_payment_id or not payload.razorpay_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="razorpay_payment_id and razorpay_signature are required",
        )

    granted_course_ids: list[uuid.UUID] = []

    async def _grant_and_capture(db_: AsyncSession, *, order: Order) -> Any:
        grants = await entitlement_service.grant_for_order(db_, order=order)
        for g in grants:
            granted_course_ids.append(g.course_id)
        return grants

    try:
        order = await order_service.confirm_order(
            db,
            user=current_user,
            order_id=order_id,
            provider_payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
            entitlement_grant_fn=_grant_and_capture,
        )
    except SignatureMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signature verification failed",
        ) from exc

    # Idempotent replays don't re-call the grant fn; backfill from existing
    # entitlements so the response shape stays consistent.
    if not granted_course_ids:
        ents = await entitlement_service.list_entitlements_for_user(
            db, user_id=current_user.id
        )
        for e in ents:
            if e.source_ref == order.id:
                granted_course_ids.append(e.course_id)

    return ConfirmOrderResponse(
        order_id=order.id,
        status=order.status,
        paid_at=order.paid_at,
        fulfilled_at=order.fulfilled_at,
        entitlements_granted=granted_course_ids,
    )


# ---------------------------------------------------------------------------
# POST /payments/free-enroll
# ---------------------------------------------------------------------------


@router.post(
    "/free-enroll",
    response_model=FreeEnrollResponse,
    status_code=status.HTTP_200_OK,
)
async def free_enroll_route(
    payload: FreeEnrollRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FreeEnrollResponse:
    """Grant a free entitlement. Idempotent — replay returns the same row."""
    try:
        ent = await entitlement_service.grant_free_course(
            db,
            user_id=current_user.id,
            course_id=payload.course_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await db.commit()
    await db.refresh(ent)

    return FreeEnrollResponse(
        course_id=ent.course_id,
        entitlement_id=ent.id,
        granted_at=ent.granted_at,
    )
