"""Pydantic schemas for the v2 payments surface (Catalog refactor 2026-04-26).

These schemas are the over-the-wire contract for the new ``/payments`` and
``/catalog`` routes. They are intentionally provider-agnostic on the response
side — Razorpay-specific fields (``razorpay_key_id``) are nullable so the same
``CreateOrderResponse`` can serve a future Stripe checkout without a schema
break.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Orders — request / response
# ---------------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    target_type: Literal["course", "bundle"]
    target_id: uuid.UUID
    provider: Literal["razorpay", "stripe"] = "razorpay"
    # When None, the route falls back to settings.payments_default_currency.
    currency: str | None = None


class CreateOrderResponse(BaseModel):
    order_id: uuid.UUID
    provider: str
    provider_order_id: str
    amount_cents: int
    currency: str
    receipt_number: str
    # Public key id the frontend needs to open the Razorpay checkout modal.
    razorpay_key_id: str | None = None
    user_email: str
    user_name: str
    # Title of the course/bundle being purchased — drives the modal description.
    target_title: str


class ConfirmOrderRequest(BaseModel):
    """Confirm-order body. Razorpay is the primary path today; the Stripe
    fields are intentionally absent so any future "session_id" / "payment_id"
    additions stay additive."""

    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_signature: str | None = None


class ConfirmOrderResponse(BaseModel):
    order_id: uuid.UUID
    status: str
    paid_at: datetime | None
    fulfilled_at: datetime | None
    # Course UUIDs whose entitlements were granted (may be >1 for bundles).
    entitlements_granted: list[uuid.UUID]


class FreeEnrollRequest(BaseModel):
    course_id: uuid.UUID


class FreeEnrollResponse(BaseModel):
    course_id: uuid.UUID
    entitlement_id: uuid.UUID
    granted_at: datetime


class PaymentAttemptItem(BaseModel):
    """Inline summary of a payment_attempt row inside the order detail view."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    provider_payment_id: str | None
    amount_cents: int
    status: str
    failure_reason: str | None = None
    attempted_at: datetime


class OrderListItem(BaseModel):
    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    target_title: str | None = None
    amount_cents: int
    currency: str
    status: str
    receipt_number: str | None = None
    created_at: datetime


class OrderDetailResponse(OrderListItem):
    paid_at: datetime | None = None
    fulfilled_at: datetime | None = None
    failure_reason: str | None = None
    payment_attempts: list[PaymentAttemptItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Webhook ack
# ---------------------------------------------------------------------------


class WebhookAck(BaseModel):
    received: bool = True
    duplicate: bool = False
    event_type: str | None = None


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class CatalogCourseResponse(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    price_cents: int
    # For now always == settings.payments_default_currency; per-course currency
    # overrides arrive in a later phase.
    currency: str
    is_published: bool
    difficulty: str
    bullets: list[dict]
    metadata: dict
    # Per-user. False for anon callers.
    is_unlocked: bool = False


class CatalogBundleResponse(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    price_cents: int
    currency: str
    course_ids: list[uuid.UUID]
    metadata: dict
    is_published: bool


class CatalogResponse(BaseModel):
    courses: list[CatalogCourseResponse]
    bundles: list[CatalogBundleResponse]
