"""Portfolio autopsy endpoint (P2-12).

POST /api/v1/receipts/autopsy
  { project_title, project_description, code?, self_report? } → scored retro

Thin controller — real work lives in `portfolio_autopsy_service`.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.portfolio_autopsy_service import run_autopsy

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

    return AutopsyResponse(
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
