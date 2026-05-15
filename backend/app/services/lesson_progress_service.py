"""LessonProgressService — write path for asset + lesson progress.

Owns:
  * upserts to ``student_asset_progress`` (notebook executed,
    video position update, completion stamp).
  * rollup to ``student_progress`` (lesson-level status / completed_at)
    after every asset update.
  * the "newly unlocked lessons" diff used by the frontend to
    animate the next-card after a completion.

Reads delegate to ``LessonAccessService``. This service NEVER reads
entitlement directly — the route does that and only invokes us once
the student has access.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.models.lesson_asset import (
    NOTEBOOK_KINDS,
    ASSET_KIND_VIDEO,
    LessonAsset,
)
from app.models.student_asset_progress import (
    ASSET_PROGRESS_COMPLETED,
    ASSET_PROGRESS_IN_PROGRESS,
    ASSET_PROGRESS_NOT_STARTED,
    StudentAssetProgress,
)
from app.models.student_progress import StudentProgress
from app.services import lesson_access_service

log = structlog.get_logger()


@dataclass
class AssetProgressDelta:
    """What the caller wants to change. Field=None means leave alone."""

    watch_pct: float | None = None
    watched_seconds: int | None = None
    last_position_seconds: int | None = None
    mark_executed: bool = False
    # Mux webhook can flip this directly; otherwise it's derived from
    # watch_pct vs the lesson policy in `apply_asset_delta`.
    force_complete: bool = False


@dataclass
class ApplyResult:
    asset_progress: StudentAssetProgress
    lesson_completed_now: bool
    newly_unlocked_lesson_ids: list[uuid.UUID]


# ---------------------------------------------------------------------------
# Asset progress upsert
# ---------------------------------------------------------------------------


async def _get_or_create(
    db: AsyncSession, *, student_id: uuid.UUID, asset_id: uuid.UUID
) -> StudentAssetProgress:
    stmt = select(StudentAssetProgress).where(
        StudentAssetProgress.student_id == student_id,
        StudentAssetProgress.asset_id == asset_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    row = StudentAssetProgress(
        student_id=student_id,
        asset_id=asset_id,
        status=ASSET_PROGRESS_NOT_STARTED,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Race — another writer beat us. Re-fetch.
        await db.rollback()
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            raise
        return existing
    return row


def _derive_status(asset: LessonAsset, row: StudentAssetProgress) -> str:
    if row.completed_at is not None:
        return ASSET_PROGRESS_COMPLETED
    if asset.kind == ASSET_KIND_VIDEO:
        if row.watch_pct >= 0.99:
            return ASSET_PROGRESS_COMPLETED
        if row.watch_pct > 0:
            return ASSET_PROGRESS_IN_PROGRESS
        return ASSET_PROGRESS_NOT_STARTED
    if asset.kind in NOTEBOOK_KINDS:
        if row.executed_at is not None:
            return ASSET_PROGRESS_COMPLETED
        return ASSET_PROGRESS_NOT_STARTED
    return ASSET_PROGRESS_NOT_STARTED


async def apply_asset_delta(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    asset_id: uuid.UUID,
    delta: AssetProgressDelta,
) -> ApplyResult:
    """Apply a partial update to a student's asset progress, then roll up."""
    asset = await db.get(LessonAsset, asset_id)
    if asset is None:
        raise ValueError(f"Asset {asset_id} not found")

    row = await _get_or_create(db, student_id=student_id, asset_id=asset_id)
    now = datetime.now(UTC)

    if delta.watch_pct is not None:
        # Watch percentage is monotonically non-decreasing — a player
        # rewind shouldn't lower the recorded engagement.
        row.watch_pct = max(row.watch_pct, max(0.0, min(1.0, delta.watch_pct)))
    if delta.watched_seconds is not None:
        row.watched_seconds = max(row.watched_seconds, delta.watched_seconds)
    if delta.last_position_seconds is not None:
        row.last_position_seconds = max(0, delta.last_position_seconds)

    if delta.mark_executed and asset.kind in NOTEBOOK_KINDS:
        if row.executed_at is None:
            row.executed_at = now
        row.execution_count += 1

    if delta.force_complete and row.completed_at is None:
        row.completed_at = now

    new_status = _derive_status(asset, row)
    if new_status == ASSET_PROGRESS_COMPLETED and row.completed_at is None:
        row.completed_at = now
    row.status = new_status
    await db.flush()

    # Lesson rollup — check completion against policy.
    lesson_completed_now, newly_unlocked = await _rollup_lesson(
        db,
        student_id=student_id,
        lesson_id=asset.lesson_id,
    )

    return ApplyResult(
        asset_progress=row,
        lesson_completed_now=lesson_completed_now,
        newly_unlocked_lesson_ids=newly_unlocked,
    )


# ---------------------------------------------------------------------------
# Lesson rollup
# ---------------------------------------------------------------------------


async def _get_or_create_student_progress(
    db: AsyncSession, *, student_id: uuid.UUID, lesson_id: uuid.UUID
) -> StudentProgress:
    stmt = select(StudentProgress).where(
        StudentProgress.student_id == student_id,
        StudentProgress.lesson_id == lesson_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    row = StudentProgress(
        student_id=student_id,
        lesson_id=lesson_id,
        status="not_started",
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            raise
        return existing
    return row


async def _rollup_lesson(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    lesson_id: uuid.UUID,
) -> tuple[bool, list[uuid.UUID]]:
    """Recompute the lesson-level status from its assets.

    Returns ``(just_completed, newly_unlocked_lesson_ids)``. The unlocked
    list is the diff of "lessons that were locked before, are unlocked
    now" — derived by re-running the access service before/after.
    """
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        return False, []

    # Snapshot pre-state so we can diff for newly-unlocked lessons.
    pre_state = await lesson_access_service.build_course_state(
        db, student_id=student_id, course_id=lesson.course_id
    )
    locked_before = {
        s.lesson.id for s in pre_state if s.lock_state == "locked"
    }

    assets = (
        await lesson_access_service.load_assets_for_lessons(db, [lesson_id])
    ).get(lesson_id, [])
    progress_by_asset = await lesson_access_service.load_progress_for_student(
        db, student_id=student_id, asset_ids=[a.id for a in assets]
    )
    completion = lesson_access_service.evaluate_lesson_completion(
        lesson=lesson, assets=assets, progress_by_asset=progress_by_asset
    )

    sp_row = await _get_or_create_student_progress(
        db, student_id=student_id, lesson_id=lesson_id
    )
    was_complete = sp_row.completed_at is not None
    if completion.is_complete:
        if not was_complete:
            sp_row.completed_at = datetime.now(UTC)
        sp_row.status = "completed"
    elif completion.completion_pct > 0:
        if sp_row.completed_at is None:
            sp_row.status = "in_progress"
    await db.flush()

    just_completed = completion.is_complete and not was_complete

    newly_unlocked: list[uuid.UUID] = []
    if just_completed:
        post_state = await lesson_access_service.build_course_state(
            db, student_id=student_id, course_id=lesson.course_id
        )
        for state in post_state:
            if (
                state.lesson.id in locked_before
                and state.lock_state != "locked"
            ):
                newly_unlocked.append(state.lesson.id)

    if just_completed:
        log.info(
            "learn.lesson_completed",
            student_id=str(student_id),
            lesson_id=str(lesson_id),
            newly_unlocked=[str(x) for x in newly_unlocked],
        )

    return just_completed, newly_unlocked


# ---------------------------------------------------------------------------
# Mark-complete endpoint helper
# ---------------------------------------------------------------------------


async def force_lesson_check(
    db: AsyncSession, *, student_id: uuid.UUID, lesson_id: uuid.UUID
) -> tuple[bool, list[uuid.UUID], list[str]]:
    """Re-evaluate the lesson policy without changing any asset progress.

    Used by the explicit "mark complete" endpoint. Returns
    ``(is_complete, newly_unlocked, missing_reasons)``.
    """
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        raise ValueError(f"Lesson {lesson_id} not found")

    assets = (
        await lesson_access_service.load_assets_for_lessons(db, [lesson_id])
    ).get(lesson_id, [])
    progress_by_asset = await lesson_access_service.load_progress_for_student(
        db, student_id=student_id, asset_ids=[a.id for a in assets]
    )
    completion = lesson_access_service.evaluate_lesson_completion(
        lesson=lesson, assets=assets, progress_by_asset=progress_by_asset
    )
    if not completion.is_complete:
        return False, [], completion.missing_reasons

    just_completed, newly_unlocked = await _rollup_lesson(
        db, student_id=student_id, lesson_id=lesson_id
    )
    return True, newly_unlocked, []
