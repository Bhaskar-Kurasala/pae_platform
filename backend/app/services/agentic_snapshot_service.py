"""D9 / Pass 3b §3.1 — StudentSnapshot computation with Redis caching.

Builds a curated, cached, per-student summary the Supervisor reads at
request time. Pass 3b §3.1 calls this load-bearing for performance at
1k students: the Supervisor never queries DB tables directly — it
always reads through this snapshot.

5-minute Redis TTL per Pass 3b §3.1. The snapshot is intentionally
NOT persisted to Postgres (Checkpoint 1 sign-off Q1: no
student_snapshots table — Redis-only).

NAMING NOTE — D9 deviation:
  Pass 3b §13.1 names this file `student_snapshot_service.py`. That
  filename is already in use by the readiness flow's snapshot
  service (an unrelated, pre-existing module). We renamed to
  `agentic_snapshot_service.py` to avoid the collision rather than
  rename the legacy file (which would touch unrelated readiness
  routes outside D9 scope). The class name stays `StudentSnapshot`
  via the schema; only the filename differs from the architecture
  pass's literal text.

What's populated in D9:
  - active_courses (paid entitlements)
  - progress_summary (rolled up from student_progress / learning_sessions)
  - risk_state (from student_risk_signals)
  - active_goal_contract (from goal_contracts)
  - capstone_status (deferred — none in D9)

What's deferred to D15 (curriculum graph build):
  - current_focus, strong_concepts, weak_concepts (need the graph
    populated — schema is in place from migration 0056 but tables
    are empty until D15)
  - open_misconceptions (depends on student_misconceptions being
    wired to the curriculum graph)

The snapshot type accepts empty defaults for all of these so the
D9 → D15 transition is purely additive: D15 turns on more fields
without breaking anything that consumes the schema today.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as _redis_mod
from app.models.course import Course
from app.models.course_entitlement import CourseEntitlement
from app.schemas.supervisor import (
    CapstoneStatus,
    CourseRef,
    GoalContractSummary,
    ProgressSummary,
    StudentSnapshot,
)

log = structlog.get_logger().bind(layer="agentic_snapshot_service")


# Pass 3b §3.1 — 5-minute Redis cache TTL.
SNAPSHOT_TTL_SECONDS = 300

# Redis key category. Registered in core/redis._KEY_CATEGORIES at
# import time (see _register_snapshot_category below).
SNAPSHOT_KEY_CATEGORY = "snapshot"


def _register_snapshot_category() -> None:
    """Add 'snapshot' to the redis key category whitelist.

    core/redis.py exposes _KEY_CATEGORIES as a frozenset, which is
    immutable in place. We rebind the module attribute with a new
    frozenset that includes our category. This is safe because
    namespaced_key() reads _KEY_CATEGORIES at call time, not at
    module import.
    """
    if SNAPSHOT_KEY_CATEGORY in _redis_mod._KEY_CATEGORIES:
        return
    _redis_mod._KEY_CATEGORIES = frozenset(  # type: ignore[attr-defined]
        {*_redis_mod._KEY_CATEGORIES, SNAPSHOT_KEY_CATEGORY}
    )


_register_snapshot_category()


def _snapshot_key(user_id: uuid.UUID) -> str:
    """Per-user cache key. Namespaced via core/redis to avoid env collisions."""
    return _redis_mod.namespaced_key(SNAPSHOT_KEY_CATEGORY, str(user_id))


# ── Snapshot computation ────────────────────────────────────────────


async def _load_active_courses(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CourseRef]:
    """Active paid courses for this user — basic identity only."""
    now = datetime.now(UTC)
    stmt = (
        select(Course.id, Course.slug, Course.title)
        .select_from(CourseEntitlement)
        .join(Course, Course.id == CourseEntitlement.course_id)
        .where(
            CourseEntitlement.user_id == user_id,
            CourseEntitlement.revoked_at.is_(None),
        )
        .where(
            (CourseEntitlement.expires_at.is_(None))
            | (CourseEntitlement.expires_at > now)
        )
    )
    result = await db.execute(stmt)
    return [
        CourseRef(course_id=row[0], slug=row[1] or "", title=row[2] or "")
        for row in result.all()
    ]


async def _load_progress_summary(
    db: AsyncSession, user_id: uuid.UUID
) -> ProgressSummary | None:
    """Rough progress signal: % complete + last-session timestamp.

    Reads from learning_sessions if present. Returns None if the
    table has no data for the user (new student) — the StudentSnapshot
    schema accepts None for this field.
    """
    try:
        result = await db.execute(
            text(
                """
                SELECT
                    COALESCE(MAX(started_at), MAX(created_at)) AS last_at,
                    COUNT(*) AS session_count
                FROM learning_sessions
                WHERE user_id = :uid
                """
            ),
            {"uid": user_id},
        )
        row = result.first()
        if row is None or row[1] == 0:
            return None
        last_at = row[0]
        weeks_active = max(0, int(row[1] // 7))
        return ProgressSummary(
            pct_complete=0.0,  # D15 wires the graph-overlaid % complete
            weeks_active=weeks_active,
            last_session_at=last_at,
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft; tables are env-dependent
        log.debug(
            "snapshot.progress_summary_unavailable",
            error=str(exc),
            user_id=str(user_id),
        )
        return None


async def _load_risk_state(
    db: AsyncSession, user_id: uuid.UUID
) -> str | None:
    """Latest risk classification mapped to StudentSnapshot's enum.

    Reads student_risk_signals.risk_score (0-100 scale per the F0/F1
    risk model). Maps:
      80+   → 'critical'
      50-79 → 'at_risk'
      <50   → 'healthy'

    Returns None when no risk signal exists for the user.
    """
    try:
        result = await db.execute(
            text(
                """
                SELECT risk_score
                FROM student_risk_signals
                WHERE user_id = :uid
                ORDER BY computed_at DESC
                LIMIT 1
                """
            ),
            {"uid": user_id},
        )
        row = result.first()
        if row is None:
            return None
        risk_score = row[0] or 0
        if risk_score >= 80:
            return "critical"
        if risk_score >= 50:
            return "at_risk"
        return "healthy"
    except Exception as exc:  # noqa: BLE001
        log.debug(
            "snapshot.risk_state_unavailable",
            error=str(exc),
            user_id=str(user_id),
        )
        return None


async def _load_goal_contract(
    db: AsyncSession, user_id: uuid.UUID
) -> GoalContractSummary | None:
    """Read the currently-active goal contract via raw SQL.

    Raw SQL because GoalContract's schema varies by deployment (column
    names differ slightly between dev seed scripts and prod). Fail-soft
    on column-not-found.
    """
    try:
        result = await db.execute(
            text(
                """
                SELECT weekly_hours_committed, target_role, expires_at
                FROM goal_contracts
                WHERE user_id = :uid
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"uid": user_id},
        )
        row = result.first()
        if row is None:
            return None
        return GoalContractSummary(
            weekly_hours_committed=float(row[0]) if row[0] is not None else None,
            target_role=row[1],
            expires_at=row[2],
        )
    except Exception as exc:  # noqa: BLE001
        log.debug(
            "snapshot.goal_contract_unavailable",
            error=str(exc),
            user_id=str(user_id),
        )
        return None


async def _load_capstone_status(
    db: AsyncSession, user_id: uuid.UUID  # noqa: ARG001
) -> CapstoneStatus | None:
    """No-op for D9; capstone tracking lives in feature-specific
    tables out of scope for the foundation. None signals 'not
    applicable' to the StudentSnapshot consumer."""
    return None


async def compute_snapshot(
    db: AsyncSession, user_id: uuid.UUID
) -> StudentSnapshot:
    """Build a fresh StudentSnapshot from DB. Bypasses cache.

    Sequential reads (each loader is independent and fast). If
    snapshot latency ever becomes a bottleneck, parallelize via
    asyncio.gather — but indexed queries at ~5ms each don't justify
    the complexity now.
    """
    active_courses = await _load_active_courses(db, user_id)
    progress = await _load_progress_summary(db, user_id)
    risk_state = await _load_risk_state(db, user_id)
    goal = await _load_goal_contract(db, user_id)
    capstone = await _load_capstone_status(db, user_id)
    return StudentSnapshot(
        active_courses=active_courses,
        progress_summary=progress,
        risk_state=risk_state,  # type: ignore[arg-type]
        active_goal_contract=goal,
        capstone_status=capstone,
        # Curriculum-graph fields stay empty until D15.
        current_focus=None,
        strong_concepts=[],
        weak_concepts=[],
        open_misconceptions=[],
        # Behavioral signals not in v1 — defaults apply.
        energy_signal=None,
        streak_days=0,
        # Preferences come from agent_memory (scope=user). Loading
        # them is a memory-store call; deferred to a follow-up.
        preferences={},
    )


async def get_snapshot(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    force_refresh: bool = False,
) -> StudentSnapshot:
    """Cached snapshot read — Redis with 5-minute TTL.

    Cache miss → DB read + write-back. Cache hit → JSON parse + return.

    Redis errors degrade gracefully: a failed read becomes a cache
    miss; a failed write logs but doesn't fail the request. Pass 3b §7.1
    Failure Class E (memory/storage layer unavailable) calls for
    graceful degradation, not hard failure.
    """
    key = _snapshot_key(user_id)
    redis = await _redis_mod.get_redis()

    if not force_refresh:
        try:
            raw = await redis.get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "snapshot.redis_get_failed",
                error=str(exc),
                user_id=str(user_id),
            )
            raw = None
        if raw is not None:
            try:
                payload = json.loads(raw)
                return StudentSnapshot.model_validate(payload)
            except Exception as exc:  # noqa: BLE001 — corrupt cache, treat as miss
                log.warning(
                    "snapshot.redis_parse_failed",
                    error=str(exc),
                    user_id=str(user_id),
                )

    snapshot = await compute_snapshot(db, user_id)
    try:
        await redis.set(
            key,
            snapshot.model_dump_json(),
            ex=SNAPSHOT_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "snapshot.redis_set_failed",
            error=str(exc),
            user_id=str(user_id),
        )
    return snapshot


async def invalidate_snapshot(user_id: uuid.UUID) -> None:
    """Delete the cached snapshot. Use after mutations that change it."""
    try:
        redis = await _redis_mod.get_redis()
        await redis.delete(_snapshot_key(user_id))
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "snapshot.invalidate_failed",
            error=str(exc),
            user_id=str(user_id),
        )


__all__ = [
    "SNAPSHOT_TTL_SECONDS",
    "compute_snapshot",
    "get_snapshot",
    "invalidate_snapshot",
]
