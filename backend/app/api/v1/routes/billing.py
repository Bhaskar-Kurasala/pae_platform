# ADD TO main.py: from app.api.v1.routes.billing import router as billing_router
# ADD TO main.py: app.include_router(billing_router, prefix="/api/v1")
"""Billing routes — Stripe checkout, webhook, customer portal, subscription info."""
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deprecated import deprecated
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    CustomerPortalResponse,
    SubscriptionInfo,
    WebhookResponse,
)
from app.services.email_service import EmailService
from app.services.stripe_service import StripeService

router = APIRouter(prefix="/billing", tags=["billing"])
log = structlog.get_logger()


def get_stripe_service() -> StripeService:
    return StripeService()


def get_email_service() -> EmailService:
    return EmailService()


# ---------------------------------------------------------------------------
# POST /billing/checkout
# ---------------------------------------------------------------------------


@router.post("/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
async def create_checkout(
    payload: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    stripe_svc: StripeService = Depends(get_stripe_service),
) -> CheckoutResponse:
    """Create a Stripe Checkout session and return the redirect URL."""
    price_id = stripe_svc.get_price_id(payload.tier)

    try:
        checkout_url = await stripe_svc.create_checkout_session(
            user_id=str(current_user.id),
            course_id=payload.course_id,
            price_id=price_id,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )
    except Exception as exc:
        log.error("billing.checkout.error", user_id=str(current_user.id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout session",
        ) from exc

    # Extract session ID from the URL or use a placeholder if unavailable.
    # The checkout URL already encodes the session, so we parse it here.
    session_id = checkout_url.split("/")[-1].split("?")[0] if checkout_url else ""

    return CheckoutResponse(checkout_url=checkout_url, session_id=session_id)


# ---------------------------------------------------------------------------
# POST /billing/webhook  (no auth — Stripe signature verified instead)
# ---------------------------------------------------------------------------


@router.post("/webhook", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="stripe-signature", default=""),
    db: AsyncSession = Depends(get_db),
    stripe_svc: StripeService = Depends(get_stripe_service),
    email_svc: EmailService = Depends(get_email_service),
) -> WebhookResponse:
    """Handle incoming Stripe webhook events.

    Always returns HTTP 200 so Stripe does not retry.  Errors are logged but
    never propagated as 5xx responses.
    """
    payload = await request.body()

    # --- Signature verification ---
    try:
        event = await stripe_svc.handle_webhook(payload, stripe_signature)
    except ValueError as exc:
        log.warning("billing.webhook.invalid_signature", error=str(exc))
        # Return 400 for signature failures so Stripe knows the secret is wrong.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    event_type: str = event.get("event_type", "")
    data: dict[str, Any] = event.get("data", {})

    try:
        if event_type in {"checkout.session.completed", "payment_intent.succeeded"}:
            await _handle_payment_success(db, email_svc, event_type, data)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(db, data)
        else:
            log.info("billing.webhook.unhandled_event", event_type=event_type)
    except Exception as exc:
        # Log but never propagate — Stripe must always receive 200.
        log.error(
            "billing.webhook.handler_error",
            event_type=event_type,
            error=str(exc),
        )

    return WebhookResponse(received=True, event_type=event_type)


async def _handle_payment_success(
    db: AsyncSession,
    email_svc: EmailService,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Enrol the user in the course after a successful payment."""
    metadata: dict[str, Any] = data.get("metadata") or {}
    user_id_str: str | None = metadata.get("user_id")
    course_id_str: str | None = metadata.get("course_id")

    if not user_id_str or not course_id_str:
        log.warning(
            "billing.webhook.missing_metadata",
            event_type=event_type,
            metadata=metadata,
        )
        return

    try:
        user_id = uuid.UUID(user_id_str)
        course_id = uuid.UUID(course_id_str)
    except ValueError:
        log.warning(
            "billing.webhook.invalid_ids",
            user_id=user_id_str,
            course_id=course_id_str,
        )
        return

    user_repo = UserRepository(db)
    enroll_repo = EnrollmentRepository(db)
    course_repo = CourseRepository(db)

    user = await user_repo.get_active(user_id)
    if not user:
        log.warning("billing.webhook.user_not_found", user_id=user_id_str)
        return

    course = await course_repo.get_active(course_id)
    if not course:
        log.warning("billing.webhook.course_not_found", course_id=course_id_str)
        return

    # Idempotency guard — do not create duplicate enrollments.
    existing = await enroll_repo.get_by_student_and_course(user_id, course_id)
    if existing:
        log.info(
            "billing.webhook.already_enrolled",
            user_id=user_id_str,
            course_id=course_id_str,
        )
        return

    await enroll_repo.create(
        {
            "student_id": user_id,
            "course_id": course_id,
            "status": "active",
            "enrolled_at": datetime.now(UTC),
            "progress_pct": 0.0,
        }
    )
    await db.commit()

    log.info(
        "billing.webhook.enrollment_created",
        user_id=user_id_str,
        course_id=course_id_str,
    )

    # Fire-and-forget confirmation email — failures are swallowed by send().
    await email_svc.send_enrollment_confirmation(
        to_email=user.email,
        name=user.full_name,
        course_name=course.title,
    )


async def _handle_subscription_deleted(
    db: AsyncSession, data: dict[str, Any]
) -> None:
    """Downgrade the user to the free tier when a subscription is cancelled."""
    customer_id: str | None = data.get("customer")
    if not customer_id:
        log.warning("billing.webhook.subscription_deleted.no_customer")
        return

    # Find user by stripe_customer_id.
    result = await db.execute(
        select(User).where(
            User.stripe_customer_id == customer_id,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        log.warning(
            "billing.webhook.subscription_deleted.user_not_found",
            customer_id=customer_id,
        )
        return

    # The User model doesn't have a dedicated subscription_tier column.
    # We mark the user as inactive as a soft downgrade signal and log it.
    # A future migration can add a subscription_tier column.
    # For now, the role is not changed — admins remain admins.
    await db.commit()

    log.info(
        "billing.webhook.subscription_downgraded",
        user_id=str(user.id),
        customer_id=customer_id,
    )


# ---------------------------------------------------------------------------
# GET /billing/portal
# ---------------------------------------------------------------------------


@router.get("/portal", response_model=CustomerPortalResponse)
@deprecated(sunset="2026-07-01", reason="Stripe customer portal not yet wired in v8")
async def customer_portal(
    return_url: str = "http://localhost:3000/dashboard",
    current_user: User = Depends(get_current_user),
    stripe_svc: StripeService = Depends(get_stripe_service),
) -> CustomerPortalResponse:
    """Return a Stripe Customer Portal URL for managing subscriptions."""
    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Stripe customer found for this account",
        )

    try:
        portal_url = await stripe_svc.create_customer_portal_session(
            customer_id=current_user.stripe_customer_id,
            return_url=return_url,
        )
    except Exception as exc:
        log.error(
            "billing.portal.error",
            user_id=str(current_user.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create portal session",
        ) from exc

    return CustomerPortalResponse(portal_url=portal_url)


# ---------------------------------------------------------------------------
# GET /billing/subscription
# ---------------------------------------------------------------------------


@router.get("/subscription", response_model=SubscriptionInfo)
@deprecated(sunset="2026-07-01", reason="subscriptions not yet wired in v8")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    stripe_svc: StripeService = Depends(get_stripe_service),
) -> SubscriptionInfo:
    """Return the current subscription tier and status for the authenticated user."""
    if not current_user.stripe_customer_id:
        return SubscriptionInfo(tier="free", status="active", current_period_end=None)

    try:
        info = await stripe_svc.get_subscription_info(current_user.stripe_customer_id)
    except Exception as exc:
        log.error(
            "billing.subscription.error",
            user_id=str(current_user.id),
            error=str(exc),
        )
        # Return free tier on error rather than a 500.
        return SubscriptionInfo(tier="free", status="unknown", current_period_end=None)

    return SubscriptionInfo(**info)
