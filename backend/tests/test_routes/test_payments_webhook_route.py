"""Route tests for /api/v1/payments/webhook/{razorpay,stripe}.

The provider package is stubbed end-to-end. We patch get_provider in BOTH
the webhook ledger service and the route module so the same controllable
fake serves the record + parse + dispatch passes.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.course_entitlement import CourseEntitlement
from app.models.order import (
    ORDER_STATUS_CREATED,
    Order,
)
from app.models.payment_attempt import PaymentAttempt
from app.models.payment_webhook_event import PaymentWebhookEvent
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_user(
    db_session: AsyncSession, email: str = "wb@test.dev"
) -> User:
    user = User(
        email=email,
        full_name="Webhook Buyer",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_course(
    db_session: AsyncSession,
    *,
    slug: str = "wb-course",
    price_cents: int = 49900,
) -> Course:
    course = Course(
        title="Webhook Course",
        slug=slug,
        description="Test",
        price_cents=price_cents,
        is_published=True,
        difficulty="intermediate",
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


async def _seed_order(
    db_session: AsyncSession,
    *,
    user: User,
    course: Course,
    provider_order_id: str,
) -> Order:
    order = Order(
        user_id=user.id,
        target_type="course",
        target_id=course.id,
        amount_cents=course.price_cents,
        currency="INR",
        provider="razorpay",
        provider_order_id=provider_order_id,
        status=ORDER_STATUS_CREATED,
        receipt_number="CF-20260426-AAAAAA",
        metadata_={},
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


def _envelope(
    *,
    event_id: str,
    event_type: str,
    related_order_id: str | None = None,
    related_payment_id: str | None = None,
    raw_payload: dict | None = None,
) -> Any:
    """Build a frozen-dataclass-shaped object that quacks like WebhookEventEnvelope."""
    from app.services.payment_providers.base import WebhookEventEnvelope

    return WebhookEventEnvelope(
        provider_event_id=event_id,
        event_type=event_type,
        related_provider_order_id=related_order_id,
        related_provider_payment_id=related_payment_id,
        raw_payload=raw_payload or {},
    )


def _make_provider_stub(
    *,
    event_id: str,
    event_type: str,
    related_order_id: str | None = None,
    related_payment_id: str | None = None,
    signature_valid: bool = True,
    raw_payload: dict | None = None,
) -> MagicMock:
    provider = MagicMock()
    provider.verify_webhook_signature = MagicMock(return_value=signature_valid)
    provider.parse_webhook_event = MagicMock(
        return_value=_envelope(
            event_id=event_id,
            event_type=event_type,
            related_order_id=related_order_id,
            related_payment_id=related_payment_id,
            raw_payload=raw_payload,
        )
    )
    return provider


def _patch_provider_everywhere(
    monkeypatch: pytest.MonkeyPatch, provider: MagicMock
) -> None:
    """Patch the provider lookup in both the ledger service AND the route."""
    from app.api.v1.routes import payments_webhook
    from app.services import payment_webhook_event_service

    monkeypatch.setattr(
        payment_webhook_event_service,
        "get_provider",
        lambda name: provider,
    )
    monkeypatch.setattr(
        payments_webhook, "get_provider", lambda name: provider
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_missing_signature_returns_400(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/payments/webhook/razorpay",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_invalid_signature_records_row_but_does_not_dispatch(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider_stub(
        event_id="evt_invalid_001",
        event_type="payment.captured",
        signature_valid=False,
    )
    _patch_provider_everywhere(monkeypatch, provider)

    resp = await client.post(
        "/api/v1/payments/webhook/razorpay",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "x-razorpay-signature": "definitely-not-valid",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] is True
    assert body["duplicate"] is False
    assert body["event_type"] == "payment.captured"

    # The ledger row exists but processed_at is None because dispatch was skipped.
    rows = (
        await db_session.execute(select(PaymentWebhookEvent))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].signature_valid is False
    assert rows[0].processed_at is None


@pytest.mark.asyncio
async def test_webhook_valid_payment_captured_grants_entitlement(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(db_session)
    course = await _seed_course(db_session)
    order = await _seed_order(
        db_session,
        user=user,
        course=course,
        provider_order_id="order_rzp_capture",
    )
    user_id = user.id
    course_id = course.id
    order_id = order.id

    raw_payload = {
        "id": "evt_cap_001",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_cap_001",
                    "order_id": "order_rzp_capture",
                }
            }
        },
    }
    provider = _make_provider_stub(
        event_id="evt_cap_001",
        event_type="payment.captured",
        related_order_id="order_rzp_capture",
        related_payment_id="pay_cap_001",
        signature_valid=True,
        raw_payload=raw_payload,
    )
    _patch_provider_everywhere(monkeypatch, provider)

    resp = await client.post(
        "/api/v1/payments/webhook/razorpay",
        content=json.dumps(raw_payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-razorpay-signature": "ok",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["received"] is True
    assert body["duplicate"] is False
    assert body["event_type"] == "payment.captured"

    # Entitlement granted.
    ents = (
        await db_session.execute(
            select(CourseEntitlement).where(
                CourseEntitlement.user_id == user_id,
                CourseEntitlement.course_id == course_id,
            )
        )
    ).scalars().all()
    assert len(ents) == 1
    assert ents[0].revoked_at is None

    # PaymentAttempt rows captured.
    attempts = (
        await db_session.execute(
            select(PaymentAttempt).where(PaymentAttempt.order_id == order_id)
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].status == "captured"


@pytest.mark.asyncio
async def test_webhook_duplicate_event_id_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(db_session)
    course = await _seed_course(db_session)
    await _seed_order(
        db_session,
        user=user,
        course=course,
        provider_order_id="order_rzp_dup",
    )
    # Capture primitive ids; the ORM instances expire across the route's
    # commit/rollback boundary and re-loading them via attribute access from
    # this async fixture trips MissingGreenlet.
    user_id = user.id
    course_id = course.id

    raw_payload = {
        "id": "evt_dup_001",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_dup_001",
                    "order_id": "order_rzp_dup",
                }
            }
        },
    }
    provider = _make_provider_stub(
        event_id="evt_dup_001",
        event_type="payment.captured",
        related_order_id="order_rzp_dup",
        related_payment_id="pay_dup_001",
        signature_valid=True,
        raw_payload=raw_payload,
    )
    _patch_provider_everywhere(monkeypatch, provider)

    payload_bytes = json.dumps(raw_payload).encode()
    headers = {
        "Content-Type": "application/json",
        "x-razorpay-signature": "ok",
    }

    first = await client.post(
        "/api/v1/payments/webhook/razorpay",
        content=payload_bytes,
        headers=headers,
    )
    second = await client.post(
        "/api/v1/payments/webhook/razorpay",
        content=payload_bytes,
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True

    # Exactly one entitlement (no double-grant on replay).
    ents = (
        await db_session.execute(
            select(CourseEntitlement).where(
                CourseEntitlement.user_id == user_id,
                CourseEntitlement.course_id == course_id,
            )
        )
    ).scalars().all()
    assert len(ents) == 1


@pytest.mark.asyncio
async def test_webhook_refund_processed_revokes_entitlement(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(db_session)
    course = await _seed_course(db_session)
    order = await _seed_order(
        db_session,
        user=user,
        course=course,
        provider_order_id="order_rzp_refund",
    )
    user_id = user.id
    course_id = course.id
    order_id = order.id

    # Pre-grant an entitlement (purchase) tied to this order.
    from app.services import entitlement_service

    await entitlement_service.grant_entitlement(
        db_session,
        user_id=user_id,
        course_id=course_id,
        source="purchase",
        source_ref=order_id,
    )
    await db_session.commit()

    refund_payload = {
        "id": "evt_refund_001",
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_001",
                    "order_id": "order_rzp_refund",
                    "payment_id": "pay_refund_001",
                    "amount": 49900,
                }
            }
        },
    }
    provider = _make_provider_stub(
        event_id="evt_refund_001",
        event_type="refund.processed",
        related_order_id="order_rzp_refund",
        related_payment_id="pay_refund_001",
        signature_valid=True,
        raw_payload=refund_payload,
    )
    _patch_provider_everywhere(monkeypatch, provider)

    resp = await client.post(
        "/api/v1/payments/webhook/razorpay",
        content=json.dumps(refund_payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-razorpay-signature": "ok",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event_type"] == "refund.processed"

    # Entitlement should now be revoked.
    ents = (
        await db_session.execute(
            select(CourseEntitlement).where(
                CourseEntitlement.user_id == user_id,
                CourseEntitlement.course_id == course_id,
            )
        )
    ).scalars().all()
    assert len(ents) == 1
    assert ents[0].revoked_at is not None
