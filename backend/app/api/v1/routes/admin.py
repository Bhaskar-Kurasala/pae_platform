from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent_action import AgentAction
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


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

    total_enrollments = (
        await db.execute(select(func.count(Enrollment.id)))
    ).scalar_one()

    total_submissions = (
        await db.execute(select(func.count(ExerciseSubmission.id)))
    ).scalar_one()

    total_agent_actions = (
        await db.execute(select(func.count(AgentAction.id)))
    ).scalar_one()

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
                )
                .where(AgentAction.agent_name == name)
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
                select(func.count(AgentAction.id)).where(
                    AgentAction.student_id == student.id
                )
            )
        ).scalar_one()

        result.append(
            {
                "id": str(student.id),
                "email": student.email,
                "full_name": student.full_name,
                "created_at": student.created_at.isoformat(),
                "last_login_at": student.last_login_at.isoformat() if student.last_login_at else None,
                "lessons_completed": lessons_completed,
                "agent_interactions": agent_interactions,
                "is_active": student.is_active,
            }
        )

    return result
