"""Tailored resume API routes.

Gated behind ``settings.feature_tailored_resume_agent``. Mounted under
``/api/v1/tailored-resume``.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deprecated import deprecated
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.tailored_resume import TailoredResume
from app.models.user import User
from app.schemas.tailored_resume import (
    GenerateRequest,
    IntakeQuestion,
    IntakeStartRequest,
    IntakeStartResponse,
    QuotaResponse,
    QuotaState,
    TailoredResumeResponse,
)
from app.services.profile_aggregator import (
    build_base_resume_bundle,
    select_intake_questions,
)
from app.services.quota_service import check_quota
from app.services.tailored_resume_service import (
    CostCapExceededError,
    QuotaExceededError,
    generate_tailored_resume,
)

log = structlog.get_logger()

router = APIRouter(prefix="/tailored-resume", tags=["tailored-resume"])


def _require_feature() -> None:
    if not settings.feature_tailored_resume_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tailored resume agent is not enabled.",
        )


def _quota_state(quota: object) -> QuotaState:
    return QuotaState(
        allowed=getattr(quota, "allowed", False),
        reason=getattr(quota, "reason", "within_quota"),
        remaining_today=getattr(quota, "remaining_today", 0),
        remaining_month=getattr(quota, "remaining_month", 0),
        reset_at=getattr(quota, "reset_at", None),
    )


@router.get("/quota", response_model=QuotaResponse)
async def get_quota(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotaResponse:
    _require_feature()
    quota = await check_quota(db, user_id=current_user.id)
    return QuotaResponse(quota=_quota_state(quota))


@router.post("/intake", response_model=IntakeStartResponse)
async def start_intake(
    body: IntakeStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IntakeStartResponse:
    """Pick the dynamic intake questions and report current quota.

    The frontend calls this BEFORE rendering the form so it can skip
    questions that platform data already covers.
    """
    _require_feature()
    quota = await check_quota(db, user_id=current_user.id)
    bundle = await build_base_resume_bundle(db, user_id=current_user.id)
    questions = select_intake_questions(bundle)
    soft_gate = (bundle.resume.verdict or "").lower() == "needs_work"
    log.info(
        "tailored_resume.intake_start",
        user_id=str(current_user.id),
        questions=len(questions),
        soft_gate=soft_gate,
        jd_chars=len(body.jd_text),
    )
    return IntakeStartResponse(
        questions=[IntakeQuestion(**q) for q in questions],
        quota=_quota_state(quota),
        soft_gate=soft_gate,
    )


@router.post("/generate", response_model=TailoredResumeResponse)
async def generate(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TailoredResumeResponse:
    """Run the full tailoring pipeline and return the structured result."""
    _require_feature()
    try:
        result = await generate_tailored_resume(
            db,
            user=current_user,
            jd_text=body.jd_text,
            intake_answers=body.intake_answers,
            jd_id=body.jd_id,
        )
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "quota_exceeded",
                "reason": exc.reason,
                "reset_at": exc.reset_at.isoformat() if exc.reset_at else None,
            },
        ) from exc
    except CostCapExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "cost_cap_exceeded", "message": str(exc)},
        ) from exc

    quota = await check_quota(db, user_id=current_user.id)
    return TailoredResumeResponse(
        id=result.tailored_resume_id,
        content=result.content,
        cover_letter=result.cover_letter,
        validation=result.validation,
        quota=_quota_state(quota),
        cost_inr=result.cost_inr,
    )


@router.get("/{tailored_resume_id}/pdf")
@deprecated(sunset="2026-07-01", reason="PDF download not yet wired in v8")
async def download_pdf(
    tailored_resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Stream the resume PDF for *tailored_resume_id*.

    PDFs are stored as a BLOB on the row when MinIO/S3 isn't configured
    (Phase 1 default). Phase 2 swaps this for a pre-signed URL redirect.
    """
    _require_feature()
    result = await db.execute(
        select(TailoredResume).where(
            TailoredResume.id == tailored_resume_id,
            TailoredResume.user_id == current_user.id,
        )
    )
    tailored = result.scalar_one_or_none()
    if tailored is None or tailored.pdf_blob is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF not found")

    # Log the download for analytics — never block response on log failure.
    try:
        from app.models.generation_log import GenerationLog

        db.add(
            GenerationLog(
                user_id=current_user.id,
                tailored_resume_id=tailored.id,
                event="downloaded",
            )
        )
        await db.commit()
    except Exception as exc:  # pragma: no cover
        log.warning("tailored_resume.download_log_failed", error=str(exc))

    return Response(
        content=tailored.pdf_blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="resume-{tailored.id}.pdf"',
        },
    )
