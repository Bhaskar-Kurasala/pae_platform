"""JD Decoder API.

Routes:
  POST /api/v1/readiness/jd/decode   — paste JD text, return analysis + match score
  GET  /api/v1/readiness/jd/{hash}   — cache lookup (analysis only, no match)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.jd_decoder import JdAnalysis
from app.models.user import User
from app.schemas.jd_decoder import (
    DecodeJdRequest,
    DecodeJdResponse,
    JdAnalysisPayload,
    MatchScorePayload,
)
from app.services.jd_decoder_service import (
    CostCapExceededError,
    decode_jd,
)

log = structlog.get_logger()

router = APIRouter(
    prefix="/readiness/jd",
    tags=["readiness-jd-decoder"],
)


def _require_flag() -> None:
    if not settings.feature_jd_decoder:
        raise HTTPException(
            status_code=404,
            detail="JD decoder is not enabled in this environment.",
        )


@router.post("/decode", response_model=DecodeJdResponse)
async def post_decode_jd(
    payload: DecodeJdRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecodeJdResponse:
    _require_flag()
    try:
        result = await decode_jd(
            db, user_id=current_user.id, jd_text=payload.jd_text
        )
    except CostCapExceededError as exc:
        log.warning(
            "jd_decoder.cost_cap",
            user_id=str(current_user.id),
            detail=str(exc),
        )
        raise HTTPException(
            status_code=429,
            detail="JD decoder cost cap reached for this decode. Try again.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DecodeJdResponse(
        jd_analysis_id=result.jd_analysis_id,
        cached=result.cached,
        analysis=JdAnalysisPayload(**result.analysis),
        match_score=MatchScorePayload(**result.match_score),
    )


@router.get("/{jd_hash}", response_model=JdAnalysisPayload)
async def get_jd_analysis(
    jd_hash: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JdAnalysisPayload:
    """Read-through cache lookup. Returns 404 if the JD has not been
    decoded yet — callers should POST /decode instead.
    """
    _require_flag()
    row = (
        await db.execute(
            select(JdAnalysis).where(JdAnalysis.jd_hash == jd_hash)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="JD analysis not found")
    return JdAnalysisPayload(
        role=row.analysis.get("role") or row.parsed.get("role", ""),
        company=row.analysis.get("company")
        or row.parsed.get("company", "")
        or None,
        seniority_read=row.analysis.get("seniority_read", ""),
        must_haves=row.analysis.get("must_haves", []),
        wishlist=row.analysis.get("wishlist", []),
        filler_flags=row.analysis.get("filler_flags", []),
        culture_signals=row.analysis.get("culture_signals", []),
        wishlist_inflated=bool(row.analysis.get("wishlist_inflated", False)),
    )
