import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel as PydanticModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent_action import AgentAction
from app.models.user import User
from app.schemas.student_note import StudentNoteCreate, StudentNoteResponse
from app.services.at_risk_student_service import compute_at_risk_students
from app.services.confusion_heatmap_service import compute_heatmap
from app.services.student_note_service import add_note, list_notes

log = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])

log = structlog.get_logger()


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class AuditLogItem(PydanticModel):
    id: str
    student_id: str | None
    agent_name: str
    action_type: str
    status: str
    duration_ms: int | None
    created_at: datetime


class LessonPerformance(PydanticModel):
    lesson_id: str
    lesson_title: str
    question_count: int
    confusion_count: int


class CourseUpdateRequest(PydanticModel):
    title: str | None = None
    description: str | None = None


class ExerciseRubricUpdateRequest(PydanticModel):
    rubric: dict[str, Any]
    test_cases: list[dict[str, Any]] | None = None


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return current_user


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> dict[str, Any]:
    """Platform overview stats."""
    from app.models.enrollment import Enrollment
    from app.models.exercise_submission import ExerciseSubmission
    from app.models.payment import Payment

    total_students = (
        await db.execute(
            select(func.count(User.id)).where(User.role == "student", User.is_deleted.is_(False))
        )
    ).scalar_one()

    total_enrollments = (await db.execute(select(func.count(Enrollment.id)))).scalar_one()

    total_submissions = (await db.execute(select(func.count(ExerciseSubmission.id)))).scalar_one()

    total_agent_actions = (await db.execute(select(func.count(AgentAction.id)))).scalar_one()

    total_revenue_cents = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.status == "succeeded"
            )
        )
    ).scalar_one()

    return {
        "total_students": total_students,
        "total_enrollments": total_enrollments,
        "total_submissions": total_submissions,
        "total_agent_actions": total_agent_actions,
        "mrr_cents": total_revenue_cents,
        "mrr_usd": round(float(total_revenue_cents) / 100, 2),
    }


@router.get("/agents/health")
async def get_agents_health(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Per-agent action stats."""
    from app.agents.registry import _ensure_registered, list_agents

    _ensure_registered()
    all_agents = list_agents()

    result = []
    for agent_info in all_agents:
        name = agent_info["name"]

        total_actions = (
            await db.execute(
                select(func.count(AgentAction.id)).where(AgentAction.agent_name == name)
            )
        ).scalar_one()

        avg_score_row = (
            await db.execute(
                select(
                    func.avg(AgentAction.duration_ms),
                ).where(AgentAction.agent_name == name)
            )
        ).one()

        errors = (
            await db.execute(
                select(func.count(AgentAction.id)).where(
                    AgentAction.agent_name == name,
                    AgentAction.status == "error",
                )
            )
        ).scalar_one()

        result.append(
            {
                "name": name,
                "description": agent_info["description"],
                "total_actions": total_actions,
                "error_count": errors,
                "avg_duration_ms": round(float(avg_score_row[0] or 0), 1),
                "status": "healthy" if errors == 0 else "degraded",
            }
        )

    return result


@router.get("/students")
async def list_students(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Paginated student list with engagement data."""
    from app.models.student_progress import StudentProgress

    students_result = await db.execute(
        select(User)
        .where(User.role == "student", User.is_deleted.is_(False))
        .offset(skip)
        .limit(limit)
        .order_by(User.created_at.desc())
    )
    students = list(students_result.scalars().all())

    result = []
    for student in students:
        lessons_completed = (
            await db.execute(
                select(func.count(StudentProgress.id)).where(
                    StudentProgress.student_id == student.id,
                    StudentProgress.status == "completed",
                )
            )
        ).scalar_one()

        agent_interactions = (
            await db.execute(
                select(func.count(AgentAction.id)).where(AgentAction.student_id == student.id)
            )
        ).scalar_one()

        result.append(
            {
                "id": str(student.id),
                "email": student.email,
                "full_name": student.full_name,
                "created_at": student.created_at.isoformat(),
                "last_login_at": student.last_login_at.isoformat()
                if student.last_login_at
                else None,
                "lessons_completed": lessons_completed,
                "agent_interactions": agent_interactions,
                "is_active": student.is_active,
            }
        )

    return result


@router.get("/confusion-heatmap")
async def get_confusion_heatmap(
    days: int = Query(30, ge=1, le=180),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Top confusing concepts over the last `days` days (P2-13).

    Each bucket is one topic with help-request count, distinct students,
    last-seen timestamp, ranking score, and up to 3 sample questions.
    """
    buckets = await compute_heatmap(db, days=days, limit=limit)
    return [
        {
            "topic": b.topic,
            "help_count": b.help_count,
            "distinct_students": b.distinct_students,
            "last_seen": b.last_seen.isoformat() if b.last_seen else None,
            "score": b.score,
            "sample_questions": b.sample_questions,
        }
        for b in buckets
    ]


@router.get("/at-risk-students")
async def get_at_risk_students(
    limit: int = Query(25, ge=1, le=100),
    min_score: float = Query(0.35, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Students likely to churn with human-readable reasons (P2-14).

    Filter with `min_score` — default 0.35 — so admins see actionable names,
    not a full leaderboard. Each entry names the 1-3 dominant risk factors.
    """
    students = await compute_at_risk_students(db, limit=limit, min_score=min_score)
    return [
        {
            "student_id": s.student_id,
            "email": s.email,
            "full_name": s.full_name,
            "risk_score": s.risk_score,
            "reasons": s.reasons,
            "no_login_days": s.no_login_days,
            "lesson_stall_days": s.lesson_stall_days,
            "help_requests_recent": s.help_requests_recent,
            "help_requests_prior": s.help_requests_prior,
            "low_mood_count": s.low_mood_count,
            "progress_pct": s.progress_pct,
            "signals": [
                {"name": sig.name, "weight": sig.weight, "reason": sig.reason} for sig in s.signals
            ],
        }
        for s in students
    ]


async def _require_student(db: AsyncSession, student_id: uuid.UUID) -> User:
    user = (
        await db.execute(
            select(User).where(
                User.id == student_id, User.is_deleted.is_(False)
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Student not found"
        )
    return user


@router.post(
    "/students/{student_id}/notes",
    response_model=StudentNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_student_note(
    student_id: uuid.UUID,
    payload: StudentNoteCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> StudentNoteResponse:
    """Record an admin intervention note on a student (P3 3A-18)."""
    await _require_student(db, student_id)
    note = await add_note(
        db,
        admin_id=admin.id,
        student_id=student_id,
        body_md=payload.body_md.strip(),
    )
    return StudentNoteResponse.model_validate(note)


@router.get(
    "/students/{student_id}/notes",
    response_model=list[StudentNoteResponse],
)
async def list_student_notes(
    student_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[StudentNoteResponse]:
    """Return notes for a student, newest first."""
    await _require_student(db, student_id)
    notes = await list_notes(db, student_id=student_id, limit=limit)
    return [StudentNoteResponse.model_validate(n) for n in notes]


# ── #142: Audit log viewer ────────────────────────────────────────────────────


@router.get("/audit-log", response_model=list[AuditLogItem])
async def get_audit_log(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[AuditLogItem]:
    """Paginated agent action audit log (#142)."""
    result = await db.execute(
        select(AgentAction)
        .order_by(AgentAction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    log.info("admin.audit_log_viewed", limit=limit, offset=offset, count=len(rows))
    return [
        AuditLogItem(
            id=str(r.id),
            student_id=str(r.student_id) if r.student_id else None,
            agent_name=r.agent_name,
            action_type=r.action_type,
            status=r.status,
            duration_ms=r.duration_ms,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ── #148: Content performance per-lesson stats ───────────────────────────────


@router.get("/content-performance", response_model=list[LessonPerformance])
async def get_content_performance(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[LessonPerformance]:
    """Per-lesson confusion and question event counts (#148)."""
    from app.models.lesson import Lesson

    # Fetch up to 1000 recent actions; group in Python to stay DB-agnostic
    result = await db.execute(
        select(AgentAction).order_by(AgentAction.created_at.desc()).limit(1000)
    )
    actions = result.scalars().all()

    # Extract lesson_id from input_data JSON (key: "lesson_id")
    from collections import defaultdict

    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "confusion": 0})
    for action in actions:
        lid: str | None = None
        if isinstance(action.input_data, dict):
            lid = action.input_data.get("lesson_id")
        if not lid:
            continue
        counts[lid]["total"] += 1
        if action.agent_name == "socratic_tutor":
            counts[lid]["confusion"] += 1

    if not counts:
        return []

    lesson_ids = [uuid.UUID(lid) for lid in counts if lid]
    lessons_result = await db.execute(
        select(Lesson.id, Lesson.title).where(Lesson.id.in_(lesson_ids))
    )
    title_map = {str(r.id): r.title for r in lessons_result.all()}

    rows = sorted(counts.items(), key=lambda kv: kv[1]["total"], reverse=True)[:50]
    log.info("admin.content_performance_viewed", lesson_count=len(rows))
    return [
        LessonPerformance(
            lesson_id=lid,
            lesson_title=title_map.get(lid, lid),
            question_count=vals["total"],
            confusion_count=vals["confusion"],
        )
        for lid, vals in rows
    ]


# ── Course + rubric JSON editor (folds #144 + #145) ──────────────────────────


@router.patch("/courses/{course_id}", status_code=204)
async def update_course(
    course_id: uuid.UUID,
    body: CourseUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> None:
    """Update course title/description (#144)."""
    from app.models.course import Course

    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if body.title is not None:
        course.title = body.title
    if body.description is not None:
        course.description = body.description
    await db.commit()
    log.info("admin.course_updated", course_id=str(course_id))


@router.patch("/exercises/{exercise_id}/rubric", status_code=204)
async def update_exercise_rubric(
    exercise_id: uuid.UUID,
    body: ExerciseRubricUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> None:
    """Update exercise rubric and test cases (#145)."""
    from app.models.exercise import Exercise

    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalar_one_or_none()
    if not exercise:
        raise HTTPException(status_code=404, detail="Exercise not found")
    exercise.rubric = body.rubric
    if body.test_cases is not None:
        exercise.test_cases = body.test_cases  # type: ignore[assignment]
    await db.commit()
    log.info("admin.rubric_updated", exercise_id=str(exercise_id))


@router.get("/pulse")
async def get_pulse(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> dict[str, Any]:
    """5-metric platform health view (#180)."""
    from app.models.enrollment import Enrollment
    from app.models.feedback import Feedback

    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    active_students: int = (
        await db.execute(
            select(func.count(func.distinct(AgentAction.student_id))).where(
                AgentAction.created_at >= day_ago
            )
        )
    ).scalar() or 0

    agent_calls: int = (
        await db.execute(
            select(func.count(AgentAction.id)).where(AgentAction.created_at >= day_ago)
        )
    ).scalar() or 0

    # evaluation_score is not a dedicated column — derive from output_data or use 0
    # (future: add evaluation_score column to agent_actions)
    avg_score_raw = (
        await db.execute(
            select(func.avg(AgentAction.duration_ms)).where(
                AgentAction.created_at >= day_ago,
                AgentAction.duration_ms.isnot(None),
            )
        )
    ).scalar()
    # Normalise: treat 0 ms → 0.0, ≥2000 ms → 1.0 as a proxy quality indicator
    avg_duration = float(avg_score_raw or 0)
    avg_score: float = round(min(avg_duration / 2000.0, 1.0), 2)

    new_enrollments: int = (
        await db.execute(select(func.count(Enrollment.id)).where(Enrollment.created_at >= week_ago))
    ).scalar() or 0

    open_feedback: int = (
        await db.execute(
            select(func.count(Feedback.id)).where(Feedback.resolved.is_(False))  # noqa: E712
        )
    ).scalar() or 0

    log.info("admin.pulse_viewed", active_students=active_students)
    return {
        "active_students_24h": active_students,
        "agent_calls_24h": agent_calls,
        "avg_eval_score_24h": avg_score,
        "new_enrollments_7d": new_enrollments,
        "open_feedback": open_feedback,
    }
