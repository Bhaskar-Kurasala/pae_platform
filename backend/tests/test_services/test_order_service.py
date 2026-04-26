"""Unit tests for ``app.services.order_service``.

The provider package is mocked end-to-end (it's being implemented by a parallel
agent). Each test patches ``app.services.order_service.get_provider`` to
return a synthetic provider so the service stays exercise-able in isolation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.course import Course
from app.models.order import (
    ORDER_STATUS_FULFILLED,
    Order,
)
from app.models.payment_attempt import PaymentAttempt
from app.models.user import User
from app.services import order_service
from app.services.order_service import (
    confirm_order,
    create_order,
    generate_receipt_number,
    get_order_for_user,
    list_orders_for_user,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_user(db_session, email: str = "buyer@example.com") -> User:
    user = User(
        email=email,
        full_name="Buyer One",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_course(
    db_session,
    *,
    title: str = "AI Eng Bootcamp",
    slug: str = "ai-eng-bootcamp",
    price_cents: int = 49900,
    is_published: bool = True,
) -> Course:
    course = Course(
        title=title,
        slug=slug,
        description="Test course",
        price_cents=price_cents,
        is_published=is_published,
        difficulty="intermediate",
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


def _provider_mock(
    *,
    provider_order_id: str = "order_test_123",
    signature_valid: bool = True,
) -> MagicMock:
    """Build a synthetic provider client matching ``PaymentProviderBase``."""
    provider = MagicMock()
    provider.create_order = AsyncMock(
        return_value=MagicMock(
            provider_order_id=provider_order_id,
            amount_cents=49900,
            currency="INR",
            raw_response={},
        )
    )
    provider.verify_payment_signature = MagicMock(return_value=signature_valid)
    return provider


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def test_generate_receipt_number_is_deterministic_and_dated() -> None:
    order_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    fixed_now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)

    receipt = generate_receipt_number(order_id, now=fixed_now)

    assert receipt == "CF-20260426-123456"
    # Determinism — same inputs always yield same output.
    assert generate_receipt_number(order_id, now=fixed_now) == receipt


# ---------------------------------------------------------------------------
# create_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_for_paid_course_creates_provider_order(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session)
    provider = _provider_mock(provider_order_id="order_rzp_abc")
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: provider
    )

    order = await create_order(
        db_session,
        user=user,
        target_type="course",
        target_id=course.id,
        provider="razorpay",
    )

    assert order.id is not None
    assert order.user_id == user.id
    assert order.target_type == "course"
    assert order.target_id == course.id
    assert order.amount_cents == 49900
    assert order.provider == "razorpay"
    assert order.provider_order_id == "order_rzp_abc"
    assert order.status == "created"
    assert order.receipt_number is not None
    assert order.receipt_number.startswith("CF-")
    provider.create_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_order_rejects_unpublished_course(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(
        db_session, slug="unpublished", is_published=False
    )
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: _provider_mock()
    )

    with pytest.raises(HTTPException) as exc:
        await create_order(
            db_session,
            user=user,
            target_type="course",
            target_id=course.id,
            provider="razorpay",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_order_rejects_zero_amount(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    free_course = await _make_course(
        db_session, slug="free", price_cents=0
    )
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: _provider_mock()
    )

    with pytest.raises(HTTPException) as exc:
        await create_order(
            db_session,
            user=user,
            target_type="course",
            target_id=free_course.id,
            provider="razorpay",
        )
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# confirm_order
# ---------------------------------------------------------------------------


async def _seed_created_order(
    db_session, *, user: User, course: Course
) -> Order:
    order = Order(
        user_id=user.id,
        target_type="course",
        target_id=course.id,
        amount_cents=course.price_cents,
        currency="INR",
        provider="razorpay",
        provider_order_id="order_rzp_abc",
        status="created",
        receipt_number="CF-20260426-AAAAAA",
        metadata_={},
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


@pytest.mark.asyncio
async def test_confirm_order_idempotent_when_already_paid(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session)
    order = await _seed_created_order(db_session, user=user, course=course)

    provider = _provider_mock(signature_valid=True)
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: provider
    )
    grant_fn = AsyncMock()

    first = await confirm_order(
        db_session,
        user=user,
        order_id=order.id,
        provider_payment_id="pay_abc",
        signature="sig_abc",
        entitlement_grant_fn=grant_fn,
    )
    assert first.status == ORDER_STATUS_FULFILLED
    grant_fn.assert_awaited_once()

    # Second call must short-circuit — no new attempt row, no extra grant.
    second = await confirm_order(
        db_session,
        user=user,
        order_id=order.id,
        provider_payment_id="pay_abc",
        signature="sig_abc",
        entitlement_grant_fn=grant_fn,
    )
    assert second.id == first.id
    assert second.status == ORDER_STATUS_FULFILLED
    grant_fn.assert_awaited_once()  # still 1 — not 2

    attempts = (
        await db_session.execute(
            select(PaymentAttempt).where(PaymentAttempt.order_id == order.id)
        )
    ).scalars().all()
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_confirm_order_grants_entitlement_via_injected_fn(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session)
    order = await _seed_created_order(db_session, user=user, course=course)

    provider = _provider_mock(signature_valid=True)
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: provider
    )
    grant_fn = AsyncMock()

    await confirm_order(
        db_session,
        user=user,
        order_id=order.id,
        provider_payment_id="pay_abc",
        signature="sig_abc",
        entitlement_grant_fn=grant_fn,
    )

    grant_fn.assert_awaited_once()
    _, kwargs = grant_fn.call_args
    assert kwargs.get("order") is not None
    assert kwargs["order"].id == order.id


@pytest.mark.asyncio
async def test_confirm_order_raises_on_bad_signature(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session)
    order = await _seed_created_order(db_session, user=user, course=course)

    provider = _provider_mock(signature_valid=False)
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: provider
    )

    with pytest.raises(order_service.SignatureMismatchError):
        await confirm_order(
            db_session,
            user=user,
            order_id=order.id,
            provider_payment_id="pay_abc",
            signature="sig_bad",
            entitlement_grant_fn=AsyncMock(),
        )

    # Order must NOT have advanced past 'created'.
    fresh = await db_session.get(Order, order.id)
    assert fresh.status == "created"
    assert fresh.paid_at is None


@pytest.mark.asyncio
async def test_confirm_order_creates_payment_attempt_with_signature(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session)
    order = await _seed_created_order(db_session, user=user, course=course)

    provider = _provider_mock(signature_valid=True)
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: provider
    )

    await confirm_order(
        db_session,
        user=user,
        order_id=order.id,
        provider_payment_id="pay_xyz",
        signature="sig_abc",
        entitlement_grant_fn=AsyncMock(),
    )

    attempts = (
        await db_session.execute(
            select(PaymentAttempt).where(PaymentAttempt.order_id == order.id)
        )
    ).scalars().all()
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.provider_signature == "sig_abc"
    assert attempt.provider_payment_id == "pay_xyz"
    assert attempt.status == "captured"
    assert attempt.amount_cents == order.amount_cents

    fresh = await db_session.get(Order, order.id)
    assert fresh.status == ORDER_STATUS_FULFILLED
    assert fresh.paid_at is not None
    assert fresh.fulfilled_at is not None


# ---------------------------------------------------------------------------
# list / get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_orders_for_user_newest_first_and_scoped(
    db_session, monkeypatch
) -> None:
    alice = await _make_user(db_session, email="alice@example.com")
    bob = await _make_user(db_session, email="bob@example.com")
    course = await _make_course(db_session)

    o1 = await _seed_created_order(db_session, user=alice, course=course)
    # Pin created_at explicitly — SQLite second-resolution timestamps + same-tx
    # inserts otherwise tie and make the "newest first" assertion flaky.
    o1.created_at = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
    await db_session.commit()

    o2 = Order(
        user_id=alice.id,
        target_type="course",
        target_id=course.id,
        amount_cents=course.price_cents,
        currency="INR",
        provider="razorpay",
        provider_order_id="order_rzp_def",
        status="created",
        receipt_number="CF-20260426-BBBBBB",
        metadata_={},
        created_at=datetime(2026, 4, 26, 10, 0, tzinfo=UTC),
    )
    db_session.add(o2)
    await db_session.commit()
    await db_session.refresh(o2)

    bobs_order = Order(
        user_id=bob.id,
        target_type="course",
        target_id=course.id,
        amount_cents=course.price_cents,
        currency="INR",
        provider="razorpay",
        provider_order_id="order_rzp_bob",
        status="created",
        receipt_number="CF-20260426-CCCCCC",
        metadata_={},
        created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
    )
    db_session.add(bobs_order)
    await db_session.commit()

    results = await list_orders_for_user(db_session, user_id=alice.id)
    assert len(results) == 2
    # Newest first — o2 was inserted after o1.
    assert results[0].id == o2.id
    assert results[1].id == o1.id
    assert all(o.user_id == alice.id for o in results)

    # Scoped — alice never sees bob's order.
    fetched = await get_order_for_user(
        db_session, user_id=alice.id, order_id=bobs_order.id
    )
    assert fetched is None
