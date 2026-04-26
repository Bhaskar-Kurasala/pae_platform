"""Entitlement service — authoritative "user has access to course" logic.

This service owns the lifecycle of `course_entitlements` rows: grants on
order fulfillment, idempotent re-grants, revocations on refund, and the
fast `is_entitled` check that the lessons / exercises routes can call to
gate paid content.

Design notes:
  * The DB has a partial unique index ``(user_id, course_id)
    WHERE revoked_at IS NULL`` so at most ONE active entitlement per
    (user, course) can exist. We rely on the index to make `grant_*`
    safe under concurrent writes — second writer hits IntegrityError,
    we catch it, SELECT the existing row, return it.
  * Free + published courses are entitled implicitly so existing free-
    course enrollments keep working without a backfill.
  * Revoked rows are kept for audit; a re-grant inserts a NEW row
    because the old one is no longer in the partial unique set.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.course_bundle import CourseBundle
from app.models.course_entitlement import (
    ENTITLEMENT_SOURCE_BUNDLE,
    ENTITLEMENT_SOURCE_FREE,
    ENTITLEMENT_SOURCE_PURCHASE,
    ENTITLEMENT_SOURCES,
    CourseEntitlement,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Read-side helpers
# ---------------------------------------------------------------------------


async def _active_entitlement(
    db: AsyncSession, *, user_id: uuid.UUID, course_id: uuid.UUID
) -> CourseEntitlement | None:
    """Return the single active entitlement row, or None.

    "Active" = not revoked AND (no expiry OR expiry in the future).
    """
    now = datetime.now(UTC)
    stmt = (
        select(CourseEntitlement)
        .where(
            CourseEntitlement.user_id == user_id,
            CourseEntitlement.course_id == course_id,
            CourseEntitlement.revoked_at.is_(None),
            or_(
                CourseEntitlement.expires_at.is_(None),
                CourseEntitlement.expires_at > now,
            ),
        )
        .order_by(CourseEntitlement.granted_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def is_entitled(
    db: AsyncSession, *, user_id: uuid.UUID, course_id: uuid.UUID
) -> bool:
    """Fast "does this user have access to this course?" check.

    Returns True if EITHER:
      1. An active entitlement row exists, OR
      2. The course is free AND published (backwards-compat: existing free
         courses keep working without an entitlements backfill).
    """
    if await _active_entitlement(db, user_id=user_id, course_id=course_id):
        return True

    course = await db.get(Course, course_id)
    if course is None:
        return False
    return (course.price_cents or 0) == 0 and bool(course.is_published)


async def list_entitlements_for_user(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[CourseEntitlement]:
    """All currently-active entitlements for a user, newest grant first."""
    now = datetime.now(UTC)
    stmt = (
        select(CourseEntitlement)
        .where(
            CourseEntitlement.user_id == user_id,
            CourseEntitlement.revoked_at.is_(None),
            or_(
                CourseEntitlement.expires_at.is_(None),
                CourseEntitlement.expires_at > now,
            ),
        )
        .order_by(CourseEntitlement.granted_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Grant / revoke
# ---------------------------------------------------------------------------


async def grant_entitlement(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    source: str,
    source_ref: uuid.UUID | None = None,
) -> CourseEntitlement:
    """Idempotently grant an entitlement.

    Strategy: best-effort insert; on IntegrityError (the partial unique
    index fires) or on a pre-existing active row, return the existing
    one. This is safe under concurrent writers — at most one INSERT wins.
    """
    if source not in ENTITLEMENT_SOURCES:
        raise ValueError(
            f"Invalid entitlement source {source!r}; "
            f"must be one of {sorted(ENTITLEMENT_SOURCES)}"
        )

    # Cheap pre-check — avoids spamming integrity errors in the common case.
    existing = await _active_entitlement(
        db, user_id=user_id, course_id=course_id
    )
    if existing is not None:
        return existing

    row = CourseEntitlement(
        user_id=user_id,
        course_id=course_id,
        source=source,
        source_ref=source_ref,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Another writer beat us to it. Roll back the failed insert and
        # return whoever's already there.
        await db.rollback()
        existing = await _active_entitlement(
            db, user_id=user_id, course_id=course_id
        )
        if existing is None:
            # Should not happen — index fired but no row found. Re-raise
            # so the caller sees a real error rather than a silent None.
            raise
        return existing

    log.info(
        "entitlement.granted",
        user_id=str(user_id),
        course_id=str(course_id),
        source=source,
        source_ref=str(source_ref) if source_ref else None,
        entitlement_id=str(row.id),
    )
    return row


async def grant_for_order(
    db: AsyncSession, *, order: Any
) -> list[CourseEntitlement]:
    """Grant entitlement(s) implied by a fulfilled order.

    * target_type == "course"  → 1 entitlement (source=purchase)
    * target_type == "bundle"  → N entitlements, one per course in the
      bundle (source=bundle, all sharing source_ref=order.id).

    Idempotent — replaying the same fulfillment yields N entitlements,
    not 2N.
    """
    if order.target_type == "course":
        ent = await grant_entitlement(
            db,
            user_id=order.user_id,
            course_id=order.target_id,
            source=ENTITLEMENT_SOURCE_PURCHASE,
            source_ref=order.id,
        )
        return [ent]

    if order.target_type == "bundle":
        course_ids = await expand_bundle(db, bundle_id=order.target_id)
        grants: list[CourseEntitlement] = []
        for cid in course_ids:
            grants.append(
                await grant_entitlement(
                    db,
                    user_id=order.user_id,
                    course_id=cid,
                    source=ENTITLEMENT_SOURCE_BUNDLE,
                    source_ref=order.id,
                )
            )
        return grants

    raise ValueError(
        f"Unknown order.target_type {order.target_type!r}; "
        "expected 'course' or 'bundle'"
    )


async def grant_free_course(
    db: AsyncSession, *, user_id: uuid.UUID, course_id: uuid.UUID
) -> CourseEntitlement:
    """Explicit free-enroll. Validates the course is actually free + live.

    Even though `is_entitled` short-circuits free+published courses
    without a row, callers may want a real audit row (e.g. to log the
    "first click" enrollment). Raises ``ValueError`` on a paid course.
    """
    course = await db.get(Course, course_id)
    if course is None:
        raise ValueError(f"Course {course_id} not found")
    if (course.price_cents or 0) > 0:
        raise ValueError(
            f"Course {course_id} is not free (price_cents="
            f"{course.price_cents})"
        )
    if not course.is_published:
        raise ValueError(f"Course {course_id} is not published")

    return await grant_entitlement(
        db,
        user_id=user_id,
        course_id=course_id,
        source=ENTITLEMENT_SOURCE_FREE,
        source_ref=None,
    )


async def revoke_entitlement(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    reason: str | None = None,
) -> CourseEntitlement | None:
    """Revoke the active entitlement for (user, course).

    Returns the updated row, or None if there was no active row.
    The row is kept for audit (we just stamp ``revoked_at``).
    """
    row = await _active_entitlement(
        db, user_id=user_id, course_id=course_id
    )
    if row is None:
        return None
    row.revoked_at = datetime.now(UTC)
    await db.flush()
    log.info(
        "entitlement.revoked",
        user_id=str(user_id),
        course_id=str(course_id),
        entitlement_id=str(row.id),
        reason=reason,
    )
    return row


async def revoke_for_order(db: AsyncSession, *, order_id: uuid.UUID) -> int:
    """Refund-flow helper. Revoke every entitlement granted by this order.

    Returns the count of rows revoked. Already-revoked rows are skipped
    (we filter on ``revoked_at IS NULL``).
    """
    stmt = select(CourseEntitlement).where(
        and_(
            CourseEntitlement.source_ref == order_id,
            CourseEntitlement.revoked_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    if rows:
        await db.flush()
    log.info(
        "entitlement.revoked_for_order",
        order_id=str(order_id),
        count=len(rows),
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Bundle expansion
# ---------------------------------------------------------------------------


async def expand_bundle(
    db: AsyncSession, *, bundle_id: uuid.UUID
) -> list[uuid.UUID]:
    """Return the course UUIDs inside a bundle.

    The bundle stores `course_ids` as a JSON list of UUID strings (the
    composition is snapshotted at sale time). We parse + validate each
    one; bad/missing entries are warned and dropped rather than crashing
    the whole grant loop.
    """
    bundle = await db.get(CourseBundle, bundle_id)
    if bundle is None:
        raise ValueError(f"Bundle {bundle_id} not found")

    out: list[uuid.UUID] = []
    for raw in bundle.course_ids or []:
        if not raw:
            log.warning(
                "entitlement.bundle.empty_course_id",
                bundle_id=str(bundle_id),
            )
            continue
        try:
            out.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            log.warning(
                "entitlement.bundle.unparseable_course_id",
                bundle_id=str(bundle_id),
                raw=raw,
            )
            continue
    return out
