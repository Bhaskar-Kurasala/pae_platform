"""Path screen aggregator — assembles the constellation, ladder, and proof
wall for the /path UI from real data.

All data flows from existing tables. No new persistence.
  * constellation → skills graph + saved skill path + user skill states + goal
  * ladder lessons → student_progress + lessons + exercises (labs)
  * proof wall → exercise_submissions where shared_with_peers=true

Heavy queries fan out via asyncio.gather; the SQLAlchemy session multiplexes.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.path_summary import (
    PathLab,
    PathLesson,
    PathLevel,
    PathProofEntry,
    PathStar,
    PathSummaryResponse,
)
from app.services.goal_contract_service import GoalContractService
from app.services.progress_service import ProgressService

# The constellation always renders the same career-arc — five stepping-stone
# roles climbing toward the destination role. Course progress determines
# *which* rung the student has reached; the labels themselves are fixed so
# the screen reads as a role progression, not a course catalogue.
ROLE_LADDER: tuple[tuple[str, str], ...] = (
    ("Python Developer", "Foundations"),
    ("Data Analyst", "Pipelines"),
    ("Data Scientist", "Modeling"),
    ("ML Engineer", "Productionization"),
    ("GenAI Engineer", "Agentic systems"),
)
DEFAULT_GOAL_LABEL = "Senior\nGenAI Engineer"


def _split_label(name: str) -> str:
    """Force a single line break in the constellation label so two-word role
    names render as a stack on the small star tiles."""
    parts = name.strip().split()
    if len(parts) <= 1:
        return name
    half = (len(parts) + 1) // 2
    return f"{' '.join(parts[:half])}\n{' '.join(parts[half:])}"


def _truncate_goal(s: str) -> str:
    words = s.strip().split()[:3]
    if len(words) <= 1:
        return " ".join(words)
    half = (len(words) + 1) // 2
    return f"{' '.join(words[:half])}\n{' '.join(words[half:])}"


def _duration_minutes_for_lesson(lesson: Lesson) -> int:
    if lesson.duration_seconds and lesson.duration_seconds > 0:
        return max(1, lesson.duration_seconds // 60)
    return 30  # editorial default — feels honest for a video lesson


def _duration_minutes_for_exercise(ex: Exercise) -> int:
    """Heuristic: 1 point ≈ 0.5 min so a 50-pt lab reads as ~25 min, capped
    so even ambitious capstones don't spit out 2-hour labels."""
    if ex.points and ex.points > 0:
        return max(10, min(60, ex.points // 2))
    return 25


async def _proof_wall(db: AsyncSession, *, limit: int = 2) -> list[PathProofEntry]:
    """Top peer-shared submissions ordered by score desc.

    Joins to the user table so we can render an attribution name without a
    second round-trip from the route handler.
    """
    q = (
        select(ExerciseSubmission, User)
        .join(User, ExerciseSubmission.student_id == User.id)
        .where(
            ExerciseSubmission.shared_with_peers.is_(True),
            ExerciseSubmission.code.is_not(None),
            ExerciseSubmission.score.is_not(None),
        )
        .order_by(desc(ExerciseSubmission.score))
        .limit(limit)
    )
    rows = (await db.execute(q)).all()

    entries: list[PathProofEntry] = []
    for sub, author in rows:
        snippet = sub.code or ""
        # Trim to first ~6 lines for compact card rendering.
        lines = snippet.splitlines()[:6]
        snippet = "\n".join(lines).strip() or "(empty)"
        entries.append(
            PathProofEntry(
                submission_id=sub.id,
                code_snippet=snippet,
                author_name=author.full_name or "Anonymous",
                score=int(sub.score or 0),
                promoted=author.promoted_at is not None,
            )
        )
    return entries


async def _build_constellation(
    db: AsyncSession,
    *,
    user: User,
) -> list[PathStar]:
    """Render the fixed 5-role career arc + goal star.

    The labels themselves are stable (Python Developer → Senior GenAI
    Engineer). The user's overall course progress maps to a single rung
    on the ladder: earlier rungs are `done`, that rung is `current`, the
    rest are `upcoming`. The destination star is overridden by the
    student's goal contract when one is set.
    """
    progress, goal = await asyncio.gather(
        ProgressService(db).get_student_progress(user),
        GoalContractService(db).get_for_user(user),
    )
    overall = max(0.0, min(100.0, float(progress.overall_progress)))

    # 5 rungs split the 0–100 progress band into equal arcs. The rung the
    # student is *working through* is `current`; everything earlier is
    # `done`. A fresh student (0%) lands on rung 0 (Python Developer) as
    # current — never on `upcoming`-only, which would feel demotivating.
    rung_count = len(ROLE_LADDER)
    if overall >= 100.0:
        current_rung = rung_count - 1  # working the final rung
    else:
        current_rung = min(rung_count - 1, int(overall // (100.0 / rung_count)))

    stars: list[PathStar] = []
    for idx, (name, sub) in enumerate(ROLE_LADDER):
        if idx < current_rung:
            state = "done"
            sub_text = "Earned"
        elif idx == current_rung:
            state = "current"
            sub_text = "In progress"
        else:
            state = "upcoming"
            sub_text = sub
        stars.append(
            PathStar(
                label=_split_label(name),
                sub=sub_text,
                state=state,  # type: ignore[arg-type]
                badge=str(idx + 1),
            )
        )

    # Goal star — student's target role wins; otherwise the editorial default.
    goal_label = (
        _truncate_goal(goal.target_role)
        if goal and goal.target_role
        else DEFAULT_GOAL_LABEL
    )
    stars.append(
        PathStar(
            label=goal_label,
            sub="Destination",
            state="goal",
            badge="★",
        )
    )
    return stars


async def _labs_for_lesson(
    db: AsyncSession,
    *,
    lesson: Lesson,
    completed_lesson: bool,
    user: User,
) -> tuple[list[PathLab], int]:
    """Return (labs, completed_count). Labs are exercise rows on the lesson.

    A lab counts as "done" when the user has any non-failed submission for
    it. The first non-done lab is "current"; the rest are "locked".
    """
    ex_q = (
        select(Exercise)
        .where(Exercise.lesson_id == lesson.id, Exercise.is_deleted.is_(False))
        .order_by(Exercise.order, Exercise.created_at)
    )
    exercises = list((await db.execute(ex_q)).scalars().all())
    if not exercises:
        return [], 0

    sub_q = select(ExerciseSubmission).where(
        ExerciseSubmission.student_id == user.id,
        ExerciseSubmission.exercise_id.in_([e.id for e in exercises]),
    )
    subs = list((await db.execute(sub_q)).scalars().all())
    done_ids = {s.exercise_id for s in subs if s.status != "failed"}

    labs: list[PathLab] = []
    found_current = False
    for ex in exercises:
        if ex.id in done_ids:
            status = "done"
        elif not found_current:
            status = "current" if not completed_lesson else "done"
            found_current = status == "current"
        else:
            status = "locked"
        labs.append(
            PathLab(
                id=ex.id,
                title=ex.title,
                description=ex.description,
                duration_minutes=_duration_minutes_for_exercise(ex),
                status=status,  # type: ignore[arg-type]
            )
        )
    completed_count = sum(1 for lab in labs if lab.status == "done")
    return labs, completed_count


async def _build_levels(
    db: AsyncSession, *, user: User
) -> tuple[list[PathLevel], int, uuid.UUID | None, str | None]:
    """Build the 3-rung ladder: current course (+lessons), next track to
    unlock, and the goal step.

    Returns (levels, overall_progress, active_course_id, active_course_title).
    """
    progress = await ProgressService(db).get_student_progress(user)
    overall = int(round(progress.overall_progress))

    levels: list[PathLevel] = []
    active_course: Course | None = None
    active_title: str | None = None
    active_id: uuid.UUID | None = None

    if progress.courses:
        # Active course = highest-progress non-completed course; else the first.
        active = next(
            (c for c in progress.courses if c.progress_percentage < 100),
            progress.courses[0],
        )
        active_id = active.course_id
        active_title = active.course_title

        course_row = (
            await db.execute(select(Course).where(Course.id == active.course_id))
        ).scalar_one_or_none()
        active_course = course_row

        # Pull full Lesson rows for the active course (we need duration_seconds
        # which `LessonProgressItem` doesn't carry).
        lesson_rows = list(
            (
                await db.execute(
                    select(Lesson)
                    .where(
                        Lesson.course_id == active.course_id,
                        Lesson.is_deleted.is_(False),
                    )
                    .order_by(Lesson.order)
                )
            )
            .scalars()
            .all()
        )
        # The UI only renders ~4 lesson cards before the "track unlock"
        # rung. Pick a 4-lesson window that always includes the current
        # lesson — otherwise users 8 lessons in see only "done done done
        # done" with no "current" card to act on.
        first_unfinished_idx_full: int | None = None
        for idx, item in enumerate(active.lessons):
            if item.status != "completed":
                first_unfinished_idx_full = idx
                break

        WINDOW = 4
        if first_unfinished_idx_full is None:
            # Course already complete — show the last 4 lessons.
            window_start = max(0, len(active.lessons) - WINDOW)
        else:
            # Show 1 done lesson before the current one (for context),
            # then the current lesson, then up to 2 upcoming lessons.
            window_start = max(0, first_unfinished_idx_full - 1)
        window_end = min(len(active.lessons), window_start + WINDOW)
        windowed = active.lessons[window_start:window_end]
        # Recompute the current-index inside the window.
        first_unfinished_idx: int | None = None
        for idx, item in enumerate(windowed):
            if item.status != "completed":
                first_unfinished_idx = idx
                break

        path_lessons: list[PathLesson] = []
        for idx, item in enumerate(windowed):
            row = next((l_ for l_ in lesson_rows if l_.id == item.id), None)
            duration = _duration_minutes_for_lesson(row) if row else 30
            is_done = item.status == "completed"
            is_current = idx == first_unfinished_idx
            status: str = "done" if is_done else "current" if is_current else "upcoming"
            labs, labs_done = await _labs_for_lesson(
                db,
                lesson=row or Lesson(id=item.id, title=item.title),  # type: ignore[arg-type]
                completed_lesson=is_done,
                user=user,
            )
            lab_count = len(labs)
            meta_parts = ["Required"]
            if status == "done":
                meta_parts.append("complete")
                if labs_done:
                    meta_parts.append(
                        f"{labs_done} lab{'s' if labs_done != 1 else ''} finished"
                    )
            elif status == "current":
                meta_parts.append("today")
                if lab_count:
                    meta_parts.append(
                        f"{lab_count} lab{'s' if lab_count != 1 else ''} · tap to expand"
                    )
            else:
                meta_parts.append("upcoming")
                if lab_count:
                    meta_parts.append(
                        f"{lab_count} lab{'s' if lab_count != 1 else ''} queued"
                    )
            path_lessons.append(
                PathLesson(
                    id=item.id,
                    title=item.title,
                    meta=" · ".join(meta_parts),
                    duration_minutes=duration,
                    status=status,  # type: ignore[arg-type]
                    labs=labs,
                    labs_completed=labs_done,
                )
            )

        levels.append(
            PathLevel(
                badge="1",
                title=active.course_title,
                blurb=(
                    course_row.description.strip()
                    if course_row and course_row.description
                    else "The role you are solidifying before promotion."
                ),
                progress_percentage=int(round(active.progress_percentage)),
                lessons=path_lessons,
                state="current",
            )
        )

    # Next track to unlock — the lowest-priced course the student is NOT
    # already enrolled in. Falls back silently if every published course is
    # already enrolled.
    enrolled_ids_q = select(Enrollment.course_id).where(
        Enrollment.student_id == user.id,
        Enrollment.status == "active",
    )
    enrolled_ids = {
        row[0] for row in (await db.execute(enrolled_ids_q)).all()
    }
    upsell_q = (
        select(Course)
        .where(
            Course.is_published.is_(True),
            Course.is_deleted.is_(False),
        )
        .order_by(Course.price_cents)
    )
    upsell: Course | None = None
    for c in (await db.execute(upsell_q)).scalars().all():
        if c.id not in enrolled_ids:
            upsell = c
            break

    if upsell is not None:
        meta = upsell.metadata_ or {}
        levels.append(
            PathLevel(
                badge="2",
                title=upsell.title,
                blurb=(upsell.description or "")[:240]
                or "SQL joins that feel natural, pandas that scales, and dashboards a "
                "stakeholder reads without a walkthrough.",
                progress_percentage=0,
                lessons=[],
                state="upcoming",
                unlock_course_id=upsell.id,
                unlock_price_cents=upsell.price_cents,
                unlock_currency=str(meta.get("currency") or "USD"),
                unlock_lesson_count=meta.get("lesson_count"),
                unlock_lab_count=meta.get("lab_count"),
            )
        )

    # Goal rung — derived from the goal contract.
    goal = await GoalContractService(db).get_for_user(user)
    goal_title = (
        (goal.target_role or "").strip()
        if goal and goal.target_role
        else "Senior GenAI Engineer"
    )
    levels.append(
        PathLevel(
            badge="★",
            title=goal_title,
            blurb=(
                "Agentic systems, production RAG, LLMOps, and the credibility that "
                "comes from repeated role-earned growth."
            ),
            progress_percentage=0,
            lessons=[],
            state="goal",
        )
    )

    return levels, overall, active_id, active_title


async def build_path_summary(
    db: AsyncSession, *, user: User
) -> PathSummaryResponse:
    constellation_task = _build_constellation(db, user=user)
    levels_task = _build_levels(db, user=user)
    proof_task = _proof_wall(db)

    constellation, levels_tuple, proof = await asyncio.gather(
        constellation_task, levels_task, proof_task
    )
    levels, overall, active_id, active_title = levels_tuple

    return PathSummaryResponse(
        overall_progress=overall,
        active_course_id=active_id,
        active_course_title=active_title,
        constellation=constellation,
        levels=levels,
        proof_wall=proof,
    )


__all__ = ["build_path_summary"]
