"""Route tests for /api/v1/payments — orders + free-enroll-adjacent flows.

The provider package is mocked so these tests never touch Razorpay. We patch:
  * ``app.services.order_service.get_provider`` for create_order + confirm_order
  * (no webhook flows here — those live in test_payments_webhook_route.py)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Order Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    return str(resp.json()["access_token"])


async def _seed_course(
    db_session: AsyncSession,
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


def _make_provider_mock(
    *, provider_order_id: str = "order_rzp_abc", signature_valid: bool = True
) -> MagicMock:
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


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch get_provider in order_service to return a controllable stub."""
    from app.services import order_service

    provider = _make_provider_mock()
    monkeypatch.setattr(order_service, "get_provider", lambda name: provider)
    return provider


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/payments/orders",
        json={
            "target_type": "course",
            "target_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /payments/orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_for_published_course_returns_provider_order_id(
    client: AsyncClient,
    db_session: AsyncSession,
    stub_provider: MagicMock,
) -> None:
    course = await _seed_course(db_session)
    token = await _register_and_login(client, "buy-published@test.dev")

    resp = await client.post(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "course",
            "target_id": str(course.id),
            "provider": "razorpay",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["provider"] == "razorpay"
    assert body["provider_order_id"] == "order_rzp_abc"
    assert body["amount_cents"] == 49900
    assert body["currency"] == "INR"
    assert body["receipt_number"].startswith("CF-")
    assert body["target_title"] == course.title
    assert body["user_email"] == "buy-published@test.dev"


@pytest.mark.asyncio
async def test_create_order_for_unpublished_course_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    stub_provider: MagicMock,
) -> None:
    course = await _seed_course(
        db_session, slug="unpublished", is_published=False
    )
    token = await _register_and_login(client, "buy-unpub@test.dev")

    resp = await client.post(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "course",
            "target_id": str(course.id),
            "provider": "razorpay",
        },
    )
    # order_service raises 404 for missing/unpublished course; we surface it.
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /payments/orders/{id}/confirm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_order_with_bad_signature_returns_400(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import order_service

    course = await _seed_course(db_session)
    token = await _register_and_login(client, "bad-sig@test.dev")

    # First create an order with a passing signature stub.
    good_provider = _make_provider_mock(signature_valid=True)
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: good_provider
    )

    resp = await client.post(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "course",
            "target_id": str(course.id),
            "provider": "razorpay",
        },
    )
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["order_id"]

    # Now flip the provider so verify_payment_signature returns False.
    bad_provider = _make_provider_mock(signature_valid=False)
    monkeypatch.setattr(
        order_service, "get_provider", lambda name: bad_provider
    )

    confirm_resp = await client.post(
        f"/api/v1/payments/orders/{order_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "razorpay_order_id": "order_rzp_abc",
            "razorpay_payment_id": "pay_bad",
            "razorpay_signature": "sig_bad",
        },
    )
    assert confirm_resp.status_code == 400


@pytest.mark.asyncio
async def test_confirm_order_with_valid_signature_grants_entitlement(
    client: AsyncClient,
    db_session: AsyncSession,
    stub_provider: MagicMock,
) -> None:
    course = await _seed_course(db_session)
    token = await _register_and_login(client, "good-sig@test.dev")

    create_resp = await client.post(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "course",
            "target_id": str(course.id),
            "provider": "razorpay",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    order_id = create_resp.json()["order_id"]

    confirm_resp = await client.post(
        f"/api/v1/payments/orders/{order_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "razorpay_order_id": "order_rzp_abc",
            "razorpay_payment_id": "pay_good",
            "razorpay_signature": "sig_good",
        },
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    body = confirm_resp.json()
    assert body["status"] == "fulfilled"
    assert body["paid_at"] is not None
    assert body["fulfilled_at"] is not None
    assert len(body["entitlements_granted"]) == 1
    assert body["entitlements_granted"][0] == str(course.id)


# ---------------------------------------------------------------------------
# GET /payments/orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_orders_returns_user_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
    stub_provider: MagicMock,
) -> None:
    course = await _seed_course(db_session)
    token_alice = await _register_and_login(client, "alice@list.dev")
    token_bob = await _register_and_login(client, "bob@list.dev")

    # Alice creates one order.
    await client.post(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token_alice}"},
        json={
            "target_type": "course",
            "target_id": str(course.id),
            "provider": "razorpay",
        },
    )

    # Bob creates one order too.
    await client.post(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token_bob}"},
        json={
            "target_type": "course",
            "target_id": str(course.id),
            "provider": "razorpay",
        },
    )

    alice_list = await client.get(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    assert alice_list.status_code == 200
    alice_orders = alice_list.json()
    assert len(alice_orders) == 1
    assert alice_orders[0]["target_title"] == course.title

    bob_list = await client.get(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert bob_list.status_code == 200
    bob_orders = bob_list.json()
    assert len(bob_orders) == 1
    # Strict scoping — alice's id must not appear in bob's list.
    alice_order_ids = {o["id"] for o in alice_orders}
    bob_order_ids = {o["id"] for o in bob_orders}
    assert alice_order_ids.isdisjoint(bob_order_ids)


# ---------------------------------------------------------------------------
# GET /payments/orders/{id}/receipt.pdf
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receipt_pdf_returns_pdf_bytes(
    client: AsyncClient,
    db_session: AsyncSession,
    stub_provider: MagicMock,
) -> None:
    course = await _seed_course(db_session)
    token = await _register_and_login(client, "pdf@test.dev")

    create_resp = await client.post(
        "/api/v1/payments/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "course",
            "target_id": str(course.id),
            "provider": "razorpay",
        },
    )
    order_id = create_resp.json()["order_id"]

    pdf_resp = await client.get(
        f"/api/v1/payments/orders/{order_id}/receipt.pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf_resp.headers["content-disposition"]
    # Hand-rolled fallback PDF starts with %PDF-1.4.
    assert pdf_resp.content.startswith(b"%PDF")
