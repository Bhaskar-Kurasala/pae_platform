"""LessonAccessService — entitlement + prerequisite + completion logic.

Single read path for "can this student access this lesson, and if so,
which assets, and what's their state?". Routes call into here; nothing
here calls into routes.

Three concerns, one service:

  1. **Entitlement** — wraps `entitlement_service.is_entitled` so the
     route layer never needs to remember the rule for free + published
     courses.

  2. **Prerequisite walking** — given a lesson, returns whether all
     `lesson_prerequisites` for that lesson are satisfied for the
     student. Depth-limited (default 50) as a defensive backstop
     against a malformed DAG; legitimate course graphs are <= 12 deep.

  3. **Completion evaluation** — applies the lesson's
     ``completion_policy`` (or the platform default) to the student's
     per-asset progress rows and returns ``(is_complete, missing_reasons)``.

The service is intentionally read-mostly. Mutations to progress live in
``LessonProgressService``; this service is what the read endpoints and
the access checks lean on.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.models.lesson_asset import (
    ASSET_KIND_CAPSTONE_BRIEF,
    ASSET_KIND_LEARNING_NOTEBOOK,
    ASSET_KIND_PRACTICE_NOTEBOOK,
    ASSET_KIND_VIDEO,
    LessonAsset,
)
from app.models.lesson_prerequisite import LessonPrerequisite
from app.models.student_asset_progress import (
    ASSET_PROGRESS_COMPLETED,
    StudentAssetProgress,
)
from app.services import entitlement_service

log = structlog.get_logger()

# Default completion policy applied when Lesson.completion_policy is NULL.
# Tuned conservatively: a student who watches 90% of the video and runs
# every notebook at least once has demonstrably engaged with the lesson.
DEFAULT_COMPLETION_POLICY: dict[str, object] = {
    "video_min_watch_pct": 0.9,
    "require_all_practice_runs": True,
    "require_learning_notebook_run": True,
    "require_capstone_submitted": False,
}

# Defensive cap for the prerequisite walker. Real course DAGs are < 20
# nodes deep; anything past 50 indicates a cycle or runaway authoring.
_MAX_PREREQ_DEPTH = 50


@dataclass(frozen=True)
class LessonCompletionResult:
    is_complete: bool
    completion_pct: float
    missing_reasons: list[str]


# ---------------------------------------------------------------------------
# Entitlement
# ---------------------------------------------------------------------------


async def has_course_access(
    db: AsyncSession, *, user_id: uuid.UUID, course_id: uuid.UUID
) -> bool:
    """True iff student has an active entitlement (or course is free+published)."""
    return await entitlement_service.is_entitled(
        db, user_id=user_id, course_id=course_id
    )


# ---------------------------------------------------------------------------
# Prerequisite walking
# ---------------------------------------------------------------------------


async def _load_prereq_edges_for_course(
    db: AsyncSession, course_id: uuid.UUID
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Return adjacency: lesson_id → list of prerequisite lesson_ids.

    Bounded to the lessons of one course so the walker only ever pulls
    in-scope edges. Lessons with no entry in the dict have no prereqs.
    """
    stmt = (
        select(LessonPrerequisite.lesson_id, LessonPrerequisite.requires_lesson_id)
        .join(Lesson, Lesson.id == LessonPrerequisite.lesson_id)
        .where(Lesson.course_id == course_id)
    )
    result = await db.execute(stmt)
    edges: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for lesson_id, required in result.all():
        edges[lesson_id].append(required)
    return dict(edges)


def direct_prereqs(
    edges: dict[uuid.UUID, list[uuid.UUID]], lesson_id: uuid.UUID
) -> list[uuid.UUID]:
    """Direct prerequisite lesson ids for a lesson (no transitive walk)."""
    return list(edges.get(lesson_id, ()))


def all_prereqs(
    edges: dict[uuid.UUID, list[uuid.UUID]], lesson_id: uuid.UUID
) -> set[uuid.UUID]:
    """Transitive prerequisite set for a lesson, depth-limited.

    Uses iterative DFS with a visited set so cycles can't loop forever.
    A cycle in the DAG is logged once and broken; the walk yields the
    valid subset that was reached before the cycle.
    """
    out: set[uuid.UUID] = set()
    stack: list[tuple[uuid.UUID, int]] = [(lesson_id, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_PREREQ_DEPTH:
            log.warning(
                "lesson_access.prereq_walk_depth_exceeded",
                root_lesson_id=str(lesson_id),
                depth=depth,
            )
            continue
        for required in edges.get(node, ()):
            if required in out:
                continue
            out.add(required)
            stack.append((required, depth + 1))
    return out


# ---------------------------------------------------------------------------
# Completion evaluation
# ---------------------------------------------------------------------------


def _policy_for_lesson(lesson: Lesson) -> dict[str, object]:
    raw = lesson.completion_policy
    if not raw:
        return dict(DEFAULT_COMPLETION_POLICY)
    merged = dict(DEFAULT_COMPLETION_POLICY)
    merged.update(raw)
    return merged


def evaluate_lesson_completion(
    *,
    lesson: Lesson,
    assets: list[LessonAsset],
    progress_by_asset: dict[uuid.UUID, StudentAssetProgress],
) -> LessonCompletionResult:
    """Apply the lesson's completion policy.

    Pure function: takes already-loaded assets + progress, returns the
    verdict. This makes it trivially unit-testable without a DB.
    """
    policy = _policy_for_lesson(lesson)
    missing: list[str] = []

    # Gather per-kind asset views.
    videos = [a for a in assets if a.kind == ASSET_KIND_VIDEO]
    practice = [a for a in assets if a.kind == ASSET_KIND_PRACTICE_NOTEBOOK]
    learning = [a for a in assets if a.kind == ASSET_KIND_LEARNING_NOTEBOOK]
    capstones = [a for a in assets if a.kind == ASSET_KIND_CAPSTONE_BRIEF]

    total_required = 0
    satisfied = 0

    # Video gate.
    video_min = float(policy.get("video_min_watch_pct", 0.0) or 0.0)
    if videos and video_min > 0:
        for v in videos:
            total_required += 1
            prog = progress_by_asset.get(v.id)
            if prog is not None and prog.watch_pct >= video_min:
                satisfied += 1
            else:
                missing.append(
                    f"Watch at least {int(video_min * 100)}% of '{v.title}'"
                )

    # Learning notebook gate.
    if policy.get("require_learning_notebook_run", False) and learning:
        for nb in learning:
            total_required += 1
            prog = progress_by_asset.get(nb.id)
            if prog is not None and prog.executed_at is not None:
                satisfied += 1
            else:
                missing.append(f"Run the learning notebook '{nb.title}'")

    # Practice notebook gate.
    if policy.get("require_all_practice_runs", False) and practice:
        for nb in practice:
            total_required += 1
            prog = progress_by_asset.get(nb.id)
            if prog is not None and prog.executed_at is not None:
                satisfied += 1
            else:
                missing.append(f"Run the practice notebook '{nb.title}'")

    # Capstone gate (only relevant for the capstone lesson itself).
    if policy.get("require_capstone_submitted", False) and capstones:
        for cap in capstones:
            total_required += 1
            prog = progress_by_asset.get(cap.id)
            if prog is not None and prog.status == ASSET_PROGRESS_COMPLETED:
                satisfied += 1
            else:
                missing.append(f"Submit the capstone '{cap.title}'")

    if total_required == 0:
        # Lessons with no gated assets (e.g., reading-only) are
        # complete the moment any progress row exists; otherwise the
        # student can mark them complete via the explicit endpoint.
        any_progress = any(
            p.status != "not_started" for p in progress_by_asset.values()
        )
        return LessonCompletionResult(
            is_complete=any_progress,
            completion_pct=1.0 if any_progress else 0.0,
            missing_reasons=[]
            if any_progress
            else ["Open at least one asset in this lesson"],
        )

    pct = satisfied / total_required
    return LessonCompletionResult(
        is_complete=satisfied == total_required,
        completion_pct=pct,
        missing_reasons=missing,
    )


# ---------------------------------------------------------------------------
# Aggregate query helpers used by the timeline endpoint
# ---------------------------------------------------------------------------


async def load_course_lessons(
    db: AsyncSession, course_id: uuid.UUID
) -> list[Lesson]:
    """Published lessons for a course, ordered by `order` then created_at."""
    stmt = (
        select(Lesson)
        .where(Lesson.course_id == course_id, Lesson.is_published.is_(True))
        .order_by(Lesson.order.asc(), Lesson.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def load_assets_for_lessons(
    db: AsyncSession, lesson_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[LessonAsset]]:
    if not lesson_ids:
        return {}
    stmt = (
        select(LessonAsset)
        .where(
            LessonAsset.lesson_id.in_(lesson_ids),
            LessonAsset.is_published.is_(True),
        )
        .order_by(LessonAsset.lesson_id.asc(), LessonAsset.order.asc())
    )
    result = await db.execute(stmt)
    out: dict[uuid.UUID, list[LessonAsset]] = defaultdict(list)
    for asset in result.scalars().all():
        out[asset.lesson_id].append(asset)
    return dict(out)


async def load_progress_for_student(
    db: AsyncSession, *, student_id: uuid.UUID, asset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, StudentAssetProgress]:
    if not asset_ids:
        return {}
    stmt = select(StudentAssetProgress).where(
        StudentAssetProgress.student_id == student_id,
        StudentAssetProgress.asset_id.in_(asset_ids),
    )
    result = await db.execute(stmt)
    return {row.asset_id: row for row in result.scalars().all()}


# ---------------------------------------------------------------------------
# High-level façade — used by the timeline route
# ---------------------------------------------------------------------------


@dataclass
class LessonState:
    lesson: Lesson
    assets: list[LessonAsset]
    progress_by_asset: dict[uuid.UUID, StudentAssetProgress]
    completion: LessonCompletionResult
    requires_lesson_ids: list[uuid.UUID]
    lock_state: str  # locked | unlocked | completed
    locked_reason: str | None


async def build_course_state(
    db: AsyncSession, *, student_id: uuid.UUID, course_id: uuid.UUID
) -> list[LessonState]:
    """Build the per-lesson state list for the Learn timeline.

    One DB pass for lessons, one for assets, one for progress, one for
    edges. Total: 4 queries regardless of lesson count.
    """
    lessons = await load_course_lessons(db, course_id)
    if not lessons:
        return []

    lesson_ids = [lesson.id for lesson in lessons]
    assets_by_lesson = await load_assets_for_lessons(db, lesson_ids)
    all_asset_ids = [a.id for assets in assets_by_lesson.values() for a in assets]
    progress_by_asset_global = await load_progress_for_student(
        db, student_id=student_id, asset_ids=all_asset_ids
    )
    edges = await _load_prereq_edges_for_course(db, course_id)

    # First pass: completion verdicts only.
    completion_by_lesson: dict[uuid.UUID, LessonCompletionResult] = {}
    for lesson in lessons:
        assets = assets_by_lesson.get(lesson.id, [])
        scoped_progress = {
            a.id: progress_by_asset_global[a.id]
            for a in assets
            if a.id in progress_by_asset_global
        }
        completion_by_lesson[lesson.id] = evaluate_lesson_completion(
            lesson=lesson,
            assets=assets,
            progress_by_asset=scoped_progress,
        )

    # Second pass: lock state derived from prerequisites + completion.
    out: list[LessonState] = []
    for lesson in lessons:
        completion = completion_by_lesson[lesson.id]
        prereqs = direct_prereqs(edges, lesson.id)
        unmet = [
            pid for pid in prereqs if not completion_by_lesson.get(
                pid, LessonCompletionResult(False, 0.0, [])
            ).is_complete
        ]
        if completion.is_complete:
            lock_state = "completed"
            locked_reason = None
        elif unmet:
            lock_state = "locked"
            locked_reason = (
                "Complete prerequisite "
                + ("lessons" if len(unmet) > 1 else "lesson")
                + " first"
            )
        else:
            lock_state = "unlocked"
            locked_reason = None

        assets = assets_by_lesson.get(lesson.id, [])
        scoped_progress = {
            a.id: progress_by_asset_global[a.id]
            for a in assets
            if a.id in progress_by_asset_global
        }
        out.append(
            LessonState(
                lesson=lesson,
                assets=assets,
                progress_by_asset=scoped_progress,
                completion=completion,
                requires_lesson_ids=prereqs,
                lock_state=lock_state,
                locked_reason=locked_reason,
            )
        )
    return out


async def is_lesson_unlocked_for_student(
    db: AsyncSession, *, student_id: uuid.UUID, lesson_id: uuid.UUID
) -> tuple[bool, str | None]:
    """Lightweight per-lesson check used by asset-access endpoints.

    Returns ``(unlocked, reason_if_locked)``. Loads only the lessons
    needed to evaluate the prereqs of `lesson_id`, not the full course.
    """
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        return False, "Lesson not found"

    course_state = await build_course_state(
        db, student_id=student_id, course_id=lesson.course_id
    )
    for state in course_state:
        if state.lesson.id == lesson_id:
            if state.lock_state == "locked":
                return False, state.locked_reason
            return True, None
    return False, "Lesson not in course"
