from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.get("/me", response_model=GoalContractResponse)
async def get_my_goal(
    service: GoalContractService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> GoalContractResponse:
    contract = await service.get_for_user(current_user)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No goal contract set for this user",
        )
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
