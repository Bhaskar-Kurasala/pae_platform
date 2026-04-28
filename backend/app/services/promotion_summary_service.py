"""Promotion screen aggregator — assembles the four ladder rungs and the
gate state for the /promotion UI from real data.

Rungs (in display order):
  1. lessons_foundation — first ~50% of the active course's lessons.
  2. lessons_complete — every lesson across active enrollments.
  3. capstone_submitted — student has submitted a capstone exercise.
  4. interviews_complete — 2+ completed practice interview sessions.

The aggregator only WRITES once: when all four rungs are done and the user
hasn't been promoted yet, the confirm endpoint flips
`users.promoted_at`/`users.promoted_to_role` so the takeover fires exactly
once. The GET endpoint is read-only and idempotent.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.interview_session import InterviewSession
from app.models.srs_card import SRSCard
from app.models.user import User
from app.schemas.promotion_summary import (
    PromotionConfirmResponse,
    PromotionRoleTransition,
    PromotionRung,
    PromotionStats,
    PromotionSummaryResponse,
)
from app.services.goal_contract_service import GoalContractService
from app.services.progress_service import ProgressService

REQUIRED_INTERVIEWS = 2
FOUNDATION_THRESHOLD = 0.5  # 50% of lessons


def _first_name(user: User) -> str | None:
    if not user.full_name:
        return None
    return user.full_name.strip().split()[0] or None


def _motivation_to_role(motivation: str | None) -> tuple[str, str]:
    """Editorial fallback when no `target_role` is on the goal contract."""
    if motivation == "career_switch":
        return "Python Developer", "Data Analyst"
    if motivation == "skill_up":
        return "Engineer", "Senior Engineer"
    if motivation == "interview":
        return "Candidate", "Hired Engineer"
    if motivation == "curiosity":
        return "Learner", "Practitioner"
    return "Python Developer", "Data Analyst"


async def _capstone_submission_count(
    db: AsyncSession, *, user_id
) -> int:
    q = (
        select(func.count(ExerciseSubmission.id))
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .where(
            Exercise.is_capstone.is_(True),
            ExerciseSubmission.student_id == user_id,
        )
    )
    return int((await db.execute(q)).scalar() or 0)


async def _completed_interview_count(
    db: AsyncSession, *, user_id
) -> int:
    q = select(func.count(InterviewSession.id)).where(
        InterviewSession.user_id == user_id,
        InterviewSession.status == "completed",
    )
    return int((await db.execute(q)).scalar() or 0)


async def _due_card_count(db: AsyncSession, *, user_id, now: datetime) -> int:
    q = select(func.count(SRSCard.id)).where(
        SRSCard.user_id == user_id,
        SRSCard.next_due_at <= now,
    )
    return int((await db.execute(q)).scalar() or 0)


def _build_rungs(
    *,
    completed_lessons: int,
    total_lessons: int,
    capstone_subs: int,
    completed_interviews: int,
) -> list[PromotionRung]:
    """Pure function — derive the 4 rungs from raw stat counts."""
    rungs: list[PromotionRung] = []

    # Rung 1: foundation — first half of lessons.
    foundation_target = max(1, int(round(total_lessons * FOUNDATION_THRESHOLD)))
    foundation_done = completed_lessons >= foundation_target if total_lessons else False
    rungs.append(
        PromotionRung(
            kind="lessons_foundation",
            title=(
                f"Lessons 1–{foundation_target} complete"
                if foundation_target > 1
                else "Lesson 1 complete"
            )
            if total_lessons
            else "Foundation lessons",
            detail="Your foundation is already in place."
            if foundation_done
            else "Build the floor every later rung sits on.",
            state="done" if foundation_done else "current",
            progress=min(
                100,
                int(round((completed_lessons / foundation_target) * 100))
                if foundation_target
                else 0,
            ),
            short_label=(
                f"Lessons 1–{foundation_target} complete"
                if foundation_target > 1
                else "Lesson 1 complete"
            ),
        )
    )

    # Rung 2: every remaining lesson.
    remaining = max(0, total_lessons - completed_lessons)
    rung2_done = remaining == 0 and total_lessons > 0
    if rung2_done:
        title2 = "All lessons complete"
        short2 = "All lessons done"
    elif remaining > 0:
        title2 = f"Finish {remaining} remaining lesson{'s' if remaining != 1 else ''}"
        short2 = (
            f"{remaining} remaining lesson{'s' if remaining != 1 else ''}"
        )
    else:
        title2 = "Finish your course"
        short2 = "Finish your course"
    state2: str
    if rung2_done:
        state2 = "done"
    elif foundation_done:
        state2 = "current"
    else:
        state2 = "locked"
    rungs.append(
        PromotionRung(
            kind="lessons_complete",
            title=title2,
            detail="APIs, testing, and collaboration close Level 1.",
            state=state2,  # type: ignore[arg-type]
            progress=int(round((completed_lessons / total_lessons) * 100))
            if total_lessons
            else 0,
            short_label=short2,
        )
    )

    # Rung 3: capstone submitted. Locked until lessons-complete is done so
    # the ladder unlocks strictly top-to-bottom — even if the student stamps
    # a draft capstone early, the visual sequence stays honest.
    rung3_done = capstone_subs > 0 and rung2_done
    rungs.append(
        PromotionRung(
            kind="capstone_submitted",
            title="Submit capstone",
            detail="One real artifact proves the role, not just attendance.",
            state=(
                "done" if rung3_done else "current" if rung2_done else "locked"
            ),
            progress=100 if rung3_done else 0,
            short_label="Capstone submitted",
        )
    )

    # Rung 4: interviews. Same ordering rule — only "current" once capstone
    # has actually crossed.
    rung4_done = completed_interviews >= REQUIRED_INTERVIEWS and rung3_done
    if rung4_done:
        state4 = "done"
    elif rung3_done:
        state4 = "current"
    else:
        state4 = "locked"
    rungs.append(
        PromotionRung(
            kind="interviews_complete",
            title=(
                f"Complete {REQUIRED_INTERVIEWS} practice interview"
                f"{'s' if REQUIRED_INTERVIEWS != 1 else ''}"
            ),
            detail="Pressure-test your thinking before the actual gate.",
            state=state4,  # type: ignore[arg-type]
            progress=min(
                100,
                int(round((completed_interviews / REQUIRED_INTERVIEWS) * 100)),
            ),
            short_label=(
                f"{REQUIRED_INTERVIEWS} practice interview"
                f"{'s' if REQUIRED_INTERVIEWS != 1 else ''}"
            ),
        )
    )
    return rungs


async def build_promotion_summary(
    db: AsyncSession, *, user: User, now: datetime | None = None
) -> PromotionSummaryResponse:
    current = now or datetime.now(UTC)

    contract_task = GoalContractService(db).get_for_user(user)
    progress_task = ProgressService(db).get_student_progress(user)
    capstone_task = _capstone_submission_count(db, user_id=user.id)
    interview_task = _completed_interview_count(db, user_id=user.id)
    due_task = _due_card_count(db, user_id=user.id, now=current)

    contract, progress, capstone_subs, completed_interviews, due_count = (
        await asyncio.gather(
            contract_task,
            progress_task,
            capstone_task,
            interview_task,
            due_task,
        )
    )

    completed_lessons = progress.lessons_completed_total
    total_lessons = progress.lessons_total

    rungs = _build_rungs(
        completed_lessons=completed_lessons,
        total_lessons=total_lessons,
        capstone_subs=capstone_subs,
        completed_interviews=completed_interviews,
    )

    all_done = all(r.state == "done" for r in rungs)
    if user.promoted_at is not None:
        gate_status = "promoted"
    elif all_done:
        gate_status = "ready_to_promote"
    else:
        gate_status = "not_ready"

    motivation = contract.motivation if contract else None
    fallback_from, fallback_to = _motivation_to_role(motivation)
    target_role = (
        contract.target_role if contract and contract.target_role else fallback_to
    )
    role = PromotionRoleTransition(from_role=fallback_from, to_role=target_role)

    overall = int(round(progress.overall_progress))

    return PromotionSummaryResponse(
        overall_progress=overall,
        rungs=rungs,
        role=role,
        stats=PromotionStats(
            completed_lessons=completed_lessons,
            total_lessons=total_lessons,
            due_card_count=due_count,
            completed_interviews=completed_interviews,
            capstone_submissions=capstone_subs,
        ),
        gate_status=gate_status,  # type: ignore[arg-type]
        promoted_at=user.promoted_at,
        promoted_to_role=user.promoted_to_role,
        user_first_name=_first_name(user),
    )


async def confirm_promotion(
    db: AsyncSession, *, user: User
) -> PromotionConfirmResponse | None:
    """Flip user.promoted_at + promoted_to_role iff the gate is ready.

    Returns None when the user isn't actually eligible. Idempotent — a
    second call after promotion is already recorded returns the existing
    timestamp.
    """
    if user.promoted_at is not None and user.promoted_to_role is not None:
        return PromotionConfirmResponse(
            promoted_at=user.promoted_at,
            promoted_to_role=user.promoted_to_role,
        )

    summary = await build_promotion_summary(db, user=user)
    if summary.gate_status != "ready_to_promote":
        return None

    user.promoted_at = datetime.now(UTC)
    user.promoted_to_role = summary.role.to_role
    await db.commit()
    await db.refresh(user)
    return PromotionConfirmResponse(
        promoted_at=user.promoted_at,  # type: ignore[arg-type]
        promoted_to_role=user.promoted_to_role,  # type: ignore[arg-type]
    )


__all__ = ["build_promotion_summary", "confirm_promotion", "_build_rungs"]
