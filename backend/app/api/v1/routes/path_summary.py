"""Path screen aggregator route — single GET that hydrates the entire
/path UI in one round-trip.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.path_summary import PathSummaryResponse
from app.services.path_summary_service import build_path_summary

router = APIRouter(prefix="/path", tags=["path"])


@router.get("/summary", response_model=PathSummaryResponse)
async def get_path_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PathSummaryResponse:
    return await build_path_summary(db, user=current_user)
