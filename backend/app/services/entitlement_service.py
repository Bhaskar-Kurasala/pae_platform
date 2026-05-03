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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import and_, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tiers import (
    DEFAULT_TIER,
    TierName,
    get_tier,
    tier_meets_minimum,
)
from app.models.course import Course
from app.models.course_bundle import CourseBundle
from app.models.course_entitlement import (
    ENTITLEMENT_SOURCE_BUNDLE,
    ENTITLEMENT_SOURCE_FREE,
    ENTITLEMENT_SOURCE_PURCHASE,
    ENTITLEMENT_SOURCES,
    CourseEntitlement,
)
from app.schemas.entitlement import (
    ActiveEntitlement,
    EntitlementContext,
    FreeTierState,
)
from app.schemas.supervisor import RateLimitState

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


# ---------------------------------------------------------------------------
# D9 / Pass 3f — EntitlementContext computation
#
# This is the single read path Layer 1, Layer 2, and Layer 3 share.
# Layer 1 (the route dependency) calls compute_active_entitlements once
# and stashes the result on request state. Layer 2 (Supervisor) reads a
# trimmed projection from SupervisorContext.entitlements. Layer 3
# (dispatch) re-fetches a fresh EntitlementContext to catch races.
#
# All three call this same function — the layered defense relies on
# them seeing the same data shape.
# ---------------------------------------------------------------------------


async def _compute_today_cost_inr(
    db: AsyncSession, user_id: uuid.UUID
) -> Decimal:
    """Look up today's accumulated agent-call cost from the materialized view.

    Reads `mv_student_daily_cost` (refreshed every 60s via Celery beat).
    Pass 3f §D acknowledges up to 60s of staleness as the cost of the
    cheap per-request lookup; the alternative is an O(N) scan of
    agent_actions per request which doesn't scale.

    Returns 0 if the view has no row for today (new user, fresh start).
    """
    today_utc = datetime.now(UTC).date()
    result = await db.execute(
        text(
            "SELECT cost_inr_total FROM mv_student_daily_cost "
            "WHERE user_id = :uid AND day_utc = :day"
        ),
        {"uid": user_id, "day": today_utc},
    )
    row = result.first()
    if row is None or row[0] is None:
        return Decimal("0")
    return Decimal(row[0])


async def _active_free_tier_grant(
    db: AsyncSession, user_id: uuid.UUID
) -> FreeTierState | None:
    """Find the longest-lived active free-tier grant for a user.

    Pass 3f §C.4: at most one active grant per (user, type) by design,
    but defensive against races — pick the one expiring latest.

    Returns None if no active grant exists.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        text(
            "SELECT id, grant_type, granted_at, expires_at, metadata "
            "FROM free_tier_grants "
            "WHERE user_id = :uid "
            "  AND revoked_at IS NULL "
            "  AND expires_at > :now "
            "ORDER BY expires_at DESC "
            "LIMIT 1"
        ),
        {"uid": user_id, "now": now},
    )
    row = result.first()
    if row is None:
        return None
    free_tier_config = get_tier("free")
    return FreeTierState(
        grant_id=row[0],
        grant_type=row[1],
        granted_at=row[2],
        expires_at=row[3],
        # Materialize the agent allow-list at construction time so
        # downstream consumers don't have to import core.tiers.
        allowed_agents=set(free_tier_config.allowed_agents),
    )


async def _active_paid_entitlements_full(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ActiveEntitlement]:
    """Return ActiveEntitlement projections for the user's active paid rows.

    Joins course_entitlements → courses to get the course slug.
    Honors the 'tier' and 'metadata' columns added in migration 0057.
    """
    now = datetime.now(UTC)
    stmt = (
        select(
            CourseEntitlement.id,
            CourseEntitlement.user_id,
            CourseEntitlement.course_id,
            Course.slug,
            CourseEntitlement.source,
            CourseEntitlement.granted_at,
            CourseEntitlement.expires_at,
            CourseEntitlement.revoked_at,
            # The tier + metadata columns added in 0057. SQLAlchemy
            # reads them as raw column expressions (not on the ORM
            # model) until a follow-up adds them to the
            # CourseEntitlement model — keeps this PR focused on the
            # service layer without a model migration.
            text("course_entitlements.tier"),
            text("course_entitlements.metadata"),
        )
        .select_from(CourseEntitlement)
        .join(Course, Course.id == CourseEntitlement.course_id)
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
    out: list[ActiveEntitlement] = []
    for row in result.all():
        out.append(
            ActiveEntitlement(
                entitlement_id=row[0],
                user_id=row[1],
                course_id=row[2],
                course_slug=row[3] or "",
                tier=row[8] or DEFAULT_TIER,
                source=row[4],
                granted_at=row[5],
                expires_at=row[6],
                revoked_at=row[7],
                metadata=row[9] or {},
            )
        )
    return out


def _resolve_effective_tier(
    paid: list[ActiveEntitlement], free: FreeTierState | None
) -> TierName:
    """Effective tier = max tier across all active grants.

    A user with both a free-tier grant AND a paid entitlement has
    effective_tier = paid (paid wins). Per Pass 3f §A.1, the free
    grant only matters for users with NO active paid entitlements.
    """
    if not paid and free is None:
        # Empty context — caller should have short-circuited at
        # Layer 1 before reaching here, but defensive default.
        return DEFAULT_TIER
    if not paid:
        return "free"
    # At least one paid row — use its tier (highest if multiple).
    tiers = [ent.tier for ent in paid]
    # Use tier_meets_minimum's order to pick the max.
    if any(tier_meets_minimum(t, "premium") for t in tiers):  # type: ignore[arg-type]
        return "premium"
    if any(tier_meets_minimum(t, "standard") for t in tiers):  # type: ignore[arg-type]
        return "standard"
    return "free"


def _resolve_cost_ceiling(
    tier: TierName, paid: list[ActiveEntitlement]
) -> Decimal:
    """Cost ceiling for the user, with metadata override support.

    Pass 3f §H.3: per-student override via
    course_entitlements.metadata['cost_ceiling_inr_override']. When
    multiple entitlements specify overrides, the largest wins (the
    user has paid for the most generous one).

    Falls back to the tier config's daily cost ceiling if no override.
    """
    base = get_tier(tier).daily_cost_ceiling_inr
    overrides: list[Decimal] = []
    for ent in paid:
        raw = ent.metadata.get("cost_ceiling_inr_override")
        if raw is None:
            continue
        try:
            overrides.append(Decimal(str(raw)))
        except (ValueError, TypeError, ArithmeticError):
            # ArithmeticError covers decimal.InvalidOperation,
            # which Decimal raises on un-parseable strings.
            log.warning(
                "entitlement.metadata.bad_cost_ceiling_override",
                user_id=str(ent.user_id),
                entitlement_id=str(ent.entitlement_id),
                raw=raw,
            )
    if not overrides:
        return base
    return max(base, max(overrides))


async def compute_active_entitlements(
    db: AsyncSession, user_id: uuid.UUID
) -> EntitlementContext:
    """Build the EntitlementContext for a user.

    Single source of truth. Read by all three enforcement layers
    (Pass 3f §A.4) so they reason over the same data shape.

    Cost: typically 3 indexed queries — paid entitlements, free-tier
    grant, today's cost rollup. ~15ms total at 1k students.
    """
    paid = await _active_paid_entitlements_full(db, user_id)
    free = await _active_free_tier_grant(db, user_id)
    effective_tier = _resolve_effective_tier(paid, free)
    cost_ceiling = _resolve_cost_ceiling(effective_tier, paid)
    cost_used = await _compute_today_cost_inr(db, user_id)
    cost_remaining = cost_ceiling - cost_used
    if cost_remaining < 0:
        # Negative remaining is fine to report — the dispatch layer
        # uses it to decline. Don't clamp at zero; observability cares
        # about how-much-over for calibration (Pass 3f §H.2).
        pass

    tier_cfg = get_tier(effective_tier)
    # Rate-limit windows: Pass 3f §B.2 puts these in TIER_CONFIGS,
    # not in DB. The "remaining" counters are simplified at the
    # service-layer for D9 — full sliding-window tracking is a
    # follow-up (the cost ceiling is the launch-blocker, rate
    # limits at the per-call granularity are calibration territory).
    now = datetime.now(UTC)
    rate_state = RateLimitState(
        burst_remaining=tier_cfg.burst_rate_limit_per_minute,
        burst_window_resets_at=now + timedelta(minutes=1),
        hourly_remaining=tier_cfg.hourly_rate_limit_per_hour,
        hourly_window_resets_at=now + timedelta(hours=1),
    )

    return EntitlementContext(
        user_id=user_id,
        active_entitlements=paid,
        free_tier=free,
        effective_tier=effective_tier,
        cost_budget_remaining_today_inr=cost_remaining,
        cost_budget_used_today_inr=cost_used,
        rate_limit_state=rate_state,
    )


async def grant_signup_grace(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    duration: timedelta = timedelta(hours=24),
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Insert a 'signup_grace' free-tier grant for a freshly-signed-up user.

    Pass 3f §C.1: 24-hour window from signup. Idempotent — calling
    twice returns the existing grant ID rather than stacking grants.
    Per Pass 3f §C.4 abuse prevention: one signup_grace per email,
    enforced by checking for an existing grant before inserting.
    """
    now = datetime.now(UTC)
    # Idempotency check: if there's already an active signup_grace,
    # return its id. Don't extend; don't stack.
    result = await db.execute(
        text(
            "SELECT id FROM free_tier_grants "
            "WHERE user_id = :uid AND grant_type = 'signup_grace' "
            "  AND revoked_at IS NULL AND expires_at > :now "
            "LIMIT 1"
        ),
        {"uid": user_id, "now": now},
    )
    row = result.first()
    if row is not None:
        return row[0]

    grant_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO free_tier_grants "
            "(id, user_id, grant_type, granted_at, expires_at, metadata) "
            "VALUES (:id, :uid, 'signup_grace', :now, :exp, :meta::jsonb)"
        ),
        {
            "id": grant_id,
            "uid": user_id,
            "now": now,
            "exp": now + duration,
            "meta": _json_dumps(metadata or {}),
        },
    )
    log.info(
        "entitlement.free_tier_granted",
        user_id=str(user_id),
        grant_type="signup_grace",
        grant_id=str(grant_id),
        expires_at=(now + duration).isoformat(),
    )
    return grant_id


async def grant_placement_quiz_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    duration: timedelta = timedelta(hours=2),
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Insert a 'placement_quiz_session' free-tier grant.

    Pass 3f §C.1: per-session free-tier window. 2-hour default — long
    enough to complete a placement quiz with breaks; short enough that
    abandoned sessions don't gate later legitimate ones.

    Idempotent: returns existing grant id when an active session is
    in flight.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        text(
            "SELECT id FROM free_tier_grants "
            "WHERE user_id = :uid AND grant_type = 'placement_quiz_session' "
            "  AND revoked_at IS NULL AND expires_at > :now "
            "LIMIT 1"
        ),
        {"uid": user_id, "now": now},
    )
    row = result.first()
    if row is not None:
        return row[0]

    grant_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO free_tier_grants "
            "(id, user_id, grant_type, granted_at, expires_at, metadata) "
            "VALUES (:id, :uid, 'placement_quiz_session', :now, :exp, :meta::jsonb)"
        ),
        {
            "id": grant_id,
            "uid": user_id,
            "now": now,
            "exp": now + duration,
            "meta": _json_dumps(metadata or {}),
        },
    )
    log.info(
        "entitlement.free_tier_granted",
        user_id=str(user_id),
        grant_type="placement_quiz_session",
        grant_id=str(grant_id),
        expires_at=(now + duration).isoformat(),
    )
    return grant_id


def _json_dumps(value: Any) -> str:
    """Compact json serialization for jsonb column inserts.

    Helper-only; using import json at the call site would be fine but
    centralizing keeps the formatting consistent in case we ever want
    to standardize timestamps or whatever.
    """
    import json as _json

    return _json.dumps(value, separators=(",", ":"), default=str)
