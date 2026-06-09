"""Feedback widget API — submit feedback (anonymous ok) + admin triage (#177)."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, get_current_user_optional
from app.models.feedback import Feedback
from app.models.user import User
from app.schemas.feedback import FeedbackCreate, FeedbackItem
from app.services.admin_audit_service import AdminAuditService

log = structlog.get_logger()
router = APIRouter(prefix="/feedback", tags=["feedback"])


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return current_user


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> dict[str, str]:
    """Submit feedback — works for authenticated users and anonymous visitors."""
    item = Feedback(
        user_id=current_user.id if current_user else None,
        route=payload.route,
        body=payload.body,
        sentiment=payload.sentiment,
        url=payload.url,
        user_agent=payload.user_agent,
        viewport_width=payload.viewport_width,
        viewport_height=payload.viewport_height,
        app_version=payload.app_version,
        category=payload.category,
        severity=payload.severity,
        error_id=payload.error_id,
        recent_route_history=payload.recent_route_history,
    )
    db.add(item)
    await db.commit()
    log.info("feedback.submitted", route=payload.route, sentiment=payload.sentiment)
    return {"id": str(item.id)}


@router.get("/admin", response_model=list[FeedbackItem])
async def list_feedback(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> list[FeedbackItem]:
    """List all feedback items newest-first (admin only)."""
    result = await db.execute(select(Feedback).order_by(Feedback.created_at.desc()).limit(200))
    items = result.scalars().all()
    log.info("admin.feedback_listed", count=len(items))
    return [FeedbackItem.model_validate(item, from_attributes=True) for item in items]


@router.patch("/admin/{feedback_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_feedback(
    feedback_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> None:
    """Mark a feedback item as resolved (admin only)."""
    result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    before = {"resolved": item.resolved}
    item.resolved = True
    await AdminAuditService.log(
        db=db,
        admin=admin,
        action_type="feedback.resolve",
        resource_type="feedback",
        resource_id=str(feedback_id),
        before=before,
        after={"resolved": True},
        request=request,
    )
    await db.commit()
    log.info("admin.feedback_resolved", feedback_id=str(feedback_id))
