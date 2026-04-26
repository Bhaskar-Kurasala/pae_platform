"""Tests for app.services.entitlement_service.

The partial unique index on `course_entitlements (user_id, course_id)
WHERE revoked_at IS NULL` lives in the Postgres migration only; the
SQLite test DB will not enforce it. The service still behaves
idempotently because it does a pre-check SELECT before insert. Tests
exercise that pre-check path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.course_bundle import CourseBundle
from app.models.course_entitlement import (
    ENTITLEMENT_SOURCE_BUNDLE,
    ENTITLEMENT_SOURCE_FREE,
    ENTITLEMENT_SOURCE_PURCHASE,
    CourseEntitlement,
)
from app.models.order import Order
from app.models.user import User
from app.services import entitlement_service

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str = "u@example.com") -> User:
    user = User(
        email=email,
        full_name="Test User",
        hashed_password="x",
        role="student",
    )
    db.add(user)
    await db.flush()
    return user


async def _make_course(
    db: AsyncSession,
    *,
    slug: str,
    price_cents: int = 9900,
    is_published: bool = True,
) -> Course:
    course = Course(
        title=f"Course {slug}",
        slug=slug,
        description="x",
        price_cents=price_cents,
        is_published=is_published,
        difficulty="beginner",
        estimated_hours=1,
    )
    db.add(course)
    await db.flush()
    return course


async def _make_bundle(
    db: AsyncSession, *, slug: str, course_ids: list[uuid.UUID]
) -> CourseBundle:
    bundle = CourseBundle(
        slug=slug,
        title=f"Bundle {slug}",
        price_cents=29900,
        course_ids=[str(cid) for cid in course_ids],
        is_published=True,
    )
    db.add(bundle)
    await db.flush()
    return bundle


async def _make_order(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    amount_cents: int = 9900,
) -> Order:
    order = Order(
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        amount_cents=amount_cents,
        currency="INR",
        provider="razorpay",
        status="fulfilled",
    )
    db.add(order)
    await db.flush()
    return order


# ---------------------------------------------------------------------------
# is_entitled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_entitled_returns_true_for_free_course_without_row(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(
        db_session, slug="free-1", price_cents=0, is_published=True
    )

    assert await entitlement_service.is_entitled(
        db_session, user_id=user.id, course_id=course.id
    )


@pytest.mark.asyncio
async def test_is_entitled_returns_true_for_active_grant(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="paid-1", price_cents=9900)

    await entitlement_service.grant_entitlement(
        db_session,
        user_id=user.id,
        course_id=course.id,
        source=ENTITLEMENT_SOURCE_PURCHASE,
    )

    assert await entitlement_service.is_entitled(
        db_session, user_id=user.id, course_id=course.id
    )


@pytest.mark.asyncio
async def test_is_entitled_returns_false_for_revoked_grant(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="paid-2", price_cents=9900)

    await entitlement_service.grant_entitlement(
        db_session,
        user_id=user.id,
        course_id=course.id,
        source=ENTITLEMENT_SOURCE_PURCHASE,
    )
    await entitlement_service.revoke_entitlement(
        db_session, user_id=user.id, course_id=course.id, reason="test"
    )

    assert not await entitlement_service.is_entitled(
        db_session, user_id=user.id, course_id=course.id
    )


@pytest.mark.asyncio
async def test_is_entitled_returns_false_for_expired_grant(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="paid-3", price_cents=9900)

    row = CourseEntitlement(
        user_id=user.id,
        course_id=course.id,
        source=ENTITLEMENT_SOURCE_PURCHASE,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(row)
    await db_session.flush()

    assert not await entitlement_service.is_entitled(
        db_session, user_id=user.id, course_id=course.id
    )


# ---------------------------------------------------------------------------
# grant_entitlement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_entitlement_idempotent_on_duplicate(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="paid-dup")

    a = await entitlement_service.grant_entitlement(
        db_session,
        user_id=user.id,
        course_id=course.id,
        source=ENTITLEMENT_SOURCE_PURCHASE,
    )
    b = await entitlement_service.grant_entitlement(
        db_session,
        user_id=user.id,
        course_id=course.id,
        source=ENTITLEMENT_SOURCE_PURCHASE,
    )

    assert a.id == b.id
    rows = await entitlement_service.list_entitlements_for_user(
        db_session, user_id=user.id
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_grant_entitlement_rejects_unknown_source(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="paid-bad-src")

    with pytest.raises(ValueError, match="Invalid entitlement source"):
        await entitlement_service.grant_entitlement(
            db_session,
            user_id=user.id,
            course_id=course.id,
            source="garbage",
        )


# ---------------------------------------------------------------------------
# grant_for_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_for_order_course_target(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="order-course")
    order = await _make_order(
        db_session,
        user_id=user.id,
        target_type="course",
        target_id=course.id,
    )

    grants = await entitlement_service.grant_for_order(
        db_session, order=order
    )

    assert len(grants) == 1
    assert grants[0].source == ENTITLEMENT_SOURCE_PURCHASE
    assert grants[0].source_ref == order.id
    assert grants[0].course_id == course.id
    assert grants[0].user_id == user.id


@pytest.mark.asyncio
async def test_grant_for_order_bundle_target(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    c1 = await _make_course(db_session, slug="b-c1")
    c2 = await _make_course(db_session, slug="b-c2")
    c3 = await _make_course(db_session, slug="b-c3")
    bundle = await _make_bundle(
        db_session, slug="bundle-3", course_ids=[c1.id, c2.id, c3.id]
    )
    order = await _make_order(
        db_session,
        user_id=user.id,
        target_type="bundle",
        target_id=bundle.id,
        amount_cents=24900,
    )

    grants = await entitlement_service.grant_for_order(
        db_session, order=order
    )

    assert len(grants) == 3
    assert {g.course_id for g in grants} == {c1.id, c2.id, c3.id}
    assert all(g.source == ENTITLEMENT_SOURCE_BUNDLE for g in grants)
    assert all(g.source_ref == order.id for g in grants)


@pytest.mark.asyncio
async def test_grant_for_order_idempotent_on_replay(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    c1 = await _make_course(db_session, slug="r-c1")
    c2 = await _make_course(db_session, slug="r-c2")
    bundle = await _make_bundle(
        db_session, slug="bundle-replay", course_ids=[c1.id, c2.id]
    )
    order = await _make_order(
        db_session,
        user_id=user.id,
        target_type="bundle",
        target_id=bundle.id,
    )

    first = await entitlement_service.grant_for_order(db_session, order=order)
    second = await entitlement_service.grant_for_order(
        db_session, order=order
    )

    assert len(first) == 2
    assert len(second) == 2
    # Same row identities — idempotent.
    assert {g.id for g in first} == {g.id for g in second}

    rows = await entitlement_service.list_entitlements_for_user(
        db_session, user_id=user.id
    )
    assert len(rows) == 2  # not 4


@pytest.mark.asyncio
async def test_grant_for_order_unknown_target_raises(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    order = await _make_order(
        db_session,
        user_id=user.id,
        target_type="mystery",
        target_id=uuid.uuid4(),
    )
    with pytest.raises(ValueError, match="Unknown order.target_type"):
        await entitlement_service.grant_for_order(db_session, order=order)


# ---------------------------------------------------------------------------
# revoke_entitlement / revoke_for_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_entitlement_sets_revoked_at(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="rev-1")

    granted = await entitlement_service.grant_entitlement(
        db_session,
        user_id=user.id,
        course_id=course.id,
        source=ENTITLEMENT_SOURCE_PURCHASE,
    )
    assert granted.revoked_at is None

    revoked = await entitlement_service.revoke_entitlement(
        db_session, user_id=user.id, course_id=course.id, reason="manual"
    )
    assert revoked is not None
    assert revoked.id == granted.id
    assert revoked.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_entitlement_returns_none_when_no_active_row(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="rev-empty")

    result = await entitlement_service.revoke_entitlement(
        db_session, user_id=user.id, course_id=course.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_revoke_for_order_revokes_all_three(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    c1 = await _make_course(db_session, slug="revo-c1")
    c2 = await _make_course(db_session, slug="revo-c2")
    c3 = await _make_course(db_session, slug="revo-c3")
    bundle = await _make_bundle(
        db_session, slug="revo-bundle", course_ids=[c1.id, c2.id, c3.id]
    )
    order = await _make_order(
        db_session,
        user_id=user.id,
        target_type="bundle",
        target_id=bundle.id,
    )
    await entitlement_service.grant_for_order(db_session, order=order)

    count = await entitlement_service.revoke_for_order(
        db_session, order_id=order.id
    )
    assert count == 3

    # All three courses now blocked (none are free).
    for cid in (c1.id, c2.id, c3.id):
        assert not await entitlement_service.is_entitled(
            db_session, user_id=user.id, course_id=cid
        )

    # Replay-safe — the second revoke does nothing.
    again = await entitlement_service.revoke_for_order(
        db_session, order_id=order.id
    )
    assert again == 0


# ---------------------------------------------------------------------------
# grant_free_course
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_free_course_rejects_paid_course(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="not-free", price_cents=9900)

    with pytest.raises(ValueError, match="not free"):
        await entitlement_service.grant_free_course(
            db_session, user_id=user.id, course_id=course.id
        )


@pytest.mark.asyncio
async def test_grant_free_course_succeeds_for_free_published_course(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(
        db_session, slug="really-free", price_cents=0, is_published=True
    )

    ent = await entitlement_service.grant_free_course(
        db_session, user_id=user.id, course_id=course.id
    )
    assert ent.source == ENTITLEMENT_SOURCE_FREE
    assert ent.source_ref is None


# ---------------------------------------------------------------------------
# expand_bundle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expand_bundle_returns_course_ids(
    db_session: AsyncSession,
) -> None:
    c1 = await _make_course(db_session, slug="exp-c1")
    c2 = await _make_course(db_session, slug="exp-c2")
    bundle = await _make_bundle(
        db_session, slug="exp-bundle", course_ids=[c1.id, c2.id]
    )

    ids = await entitlement_service.expand_bundle(
        db_session, bundle_id=bundle.id
    )
    assert set(ids) == {c1.id, c2.id}


@pytest.mark.asyncio
async def test_expand_bundle_skips_unparseable_ids(
    db_session: AsyncSession,
) -> None:
    c1 = await _make_course(db_session, slug="exp-skip-c1")
    bundle = CourseBundle(
        slug="exp-skip",
        title="Bundle skip",
        price_cents=0,
        course_ids=[str(c1.id), "not-a-uuid", ""],
        is_published=True,
    )
    db_session.add(bundle)
    await db_session.flush()

    ids = await entitlement_service.expand_bundle(
        db_session, bundle_id=bundle.id
    )
    assert ids == [c1.id]
