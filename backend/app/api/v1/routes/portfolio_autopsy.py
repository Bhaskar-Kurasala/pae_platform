"""Portfolio autopsy endpoints (P2-12).

POST /api/v1/receipts/autopsy
  { project_title, project_description, code?, self_report? } → scored retro
GET  /api/v1/receipts/autopsy            → list past autopsies (newest first)
GET  /api/v1/receipts/autopsy/{id}       → full detail for one row (own-only)

Thin controllers — real work lives in `portfolio_autopsy_service` (scoring)
and `portfolio_autopsy_persistence_service` (DB I/O).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.portfolio_autopsy_persistence import (
    PortfolioAutopsyDetailResponse,
    PortfolioAutopsyListItem,
)
from app.services.portfolio_autopsy_persistence_service import (
    get_autopsy_for_user,
    list_autopsies_for_user,
    persist_autopsy_result,
)
from app.services.portfolio_autopsy_service import run_autopsy

log = structlog.get_logger()

router = APIRouter(prefix="/receipts", tags=["receipts"])


class AutopsyRequest(BaseModel):
    project_title: str = Field(..., min_length=1, max_length=200)
    project_description: str = Field(..., min_length=20, max_length=8_000)
    code: str | None = Field(None, max_length=40_000)
    what_went_well_self: str | None = Field(None, max_length=2_000)
    what_was_hard_self: str | None = Field(None, max_length=2_000)


class AxisResponse(BaseModel):
    score: int
    assessment: str


class FindingResponse(BaseModel):
    issue: str
    why_it_matters: str
    what_to_do_differently: str


class AutopsyResponse(BaseModel):
    # `id` is the persisted `portfolio_autopsy_results.id`. Optional so a
    # persistence-failure response (best-effort path) still validates with
    # `id=None`. Frontend uses this to deep-link to the detail view without
    # a list refetch.
    id: str | None = None
    headline: str
    overall_score: int
    architecture: AxisResponse
    failure_handling: AxisResponse
    observability: AxisResponse
    scope_discipline: AxisResponse
    what_worked: list[str]
    what_to_do_differently: list[FindingResponse]
    production_gaps: list[str]
    next_project_seed: str


@router.post("/autopsy", response_model=AutopsyResponse)
async def create_autopsy(
    payload: AutopsyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutopsyResponse:
    try:
        result = await run_autopsy(
            project_title=payload.project_title,
            project_description=payload.project_description,
            code=payload.code,
            what_went_well_self=payload.what_went_well_self,
            what_was_hard_self=payload.what_was_hard_self,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Autopsy parse failed: {exc}") from exc

    # Best-effort persistence: a DB hiccup must NEVER deny the user the score.
    persisted_id: str | None = None
    try:
        persisted = await persist_autopsy_result(
            db, user=current_user, request_payload=payload, result=result
        )
        persisted_id = str(persisted.id)
    except Exception as exc:  # noqa: BLE001 — defensive; logged + swallowed.
        log.warning(
            "portfolio_autopsy.persist_failed",
            user_id=str(current_user.id),
            error=str(exc),
        )
        # Reset the session so get_db's trailing commit doesn't trip on a
        # failed transaction.
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    return AutopsyResponse(
        id=persisted_id,
        headline=result.headline,
        overall_score=result.overall_score,
        architecture=AxisResponse(**result.architecture.__dict__),
        failure_handling=AxisResponse(**result.failure_handling.__dict__),
        observability=AxisResponse(**result.observability.__dict__),
        scope_discipline=AxisResponse(**result.scope_discipline.__dict__),
        what_worked=result.what_worked,
        what_to_do_differently=[
            FindingResponse(**f.__dict__) for f in result.what_to_do_differently
        ],
        production_gaps=result.production_gaps,
        next_project_seed=result.next_project_seed,
    )


@router.get("/autopsy", response_model=list[PortfolioAutopsyListItem])
async def list_autopsies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortfolioAutopsyListItem]:
    """Newest-first list of the caller's past portfolio autopsies."""
    rows = await list_autopsies_for_user(db, user_id=current_user.id)
    return [PortfolioAutopsyListItem.model_validate(r) for r in rows]


@router.get("/autopsy/{autopsy_id}", response_model=PortfolioAutopsyDetailResponse)
async def get_autopsy(
    autopsy_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioAutopsyDetailResponse:
    """Detail view for one autopsy. 404 if absent or owned by someone else."""
    row = await get_autopsy_for_user(
        db, user_id=current_user.id, autopsy_id=autopsy_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Autopsy not found")
    return PortfolioAutopsyDetailResponse.model_validate(row)
