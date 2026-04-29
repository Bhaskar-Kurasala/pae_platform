from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deprecated import deprecated
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.goal_contract import (
    GoalContractCreate,
    GoalContractResponse,
    GoalContractUpdate,
)
from app.services.goal_contract_service import GoalContractService, days_remaining


def _to_response(contract) -> GoalContractResponse:  # type: ignore[no-untyped-def]
    base = GoalContractResponse.model_validate(contract)
    return base.model_copy(update={"days_remaining": days_remaining(contract)})

router = APIRouter(prefix="/goals", tags=["goals"])


def get_service(db: AsyncSession = Depends(get_db)) -> GoalContractService:
    return GoalContractService(db)


@router.get("/me", response_model=GoalContractResponse | None)
async def get_my_goal(
    service: GoalContractService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> GoalContractResponse | None:
    """Return the user's goal contract, or `null` when none is set.

    Originally raised 404 on absence — but every authenticated screen
    in v8 (Today, Path, Practice, Notebook, Promotion sidebar) calls
    this endpoint on mount, and a fresh-signup user has no goal yet.
    The 404s polluted browser console + Sentry breadcrumbs across
    every load. Absence-of-resource is not an error here; returning
    `null` matches the semantics the frontend hook already handles.
    The `useMyGoal` hook in `frontend/src/lib/hooks/use-goal.ts` still
    has its 404 fallback for backwards-compat with any cached response
    from older versions, but new requests hit a clean 200.
    """
    contract = await service.get_for_user(current_user)
    if contract is None:
        return None
    return _to_response(contract)


@router.post("/me", response_model=GoalContractResponse)
async def upsert_my_goal(
    payload: GoalContractCreate,
    response: Response,
    service: GoalContractService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> GoalContractResponse:
    contract, created = await service.upsert_for_user(current_user, payload)
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return _to_response(contract)


@router.patch("/me", response_model=GoalContractResponse)
@deprecated(sunset="2026-07-01", reason="frontend uses POST upsert")
async def patch_my_goal(
    payload: GoalContractUpdate,
    service: GoalContractService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> GoalContractResponse:
    contract = await service.patch_for_user(current_user, payload)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No goal contract set for this user",
        )
    return _to_response(contract)
