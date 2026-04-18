from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.goal_contract import GoalContract
from app.models.user import User
from app.schemas.skill_path import SavedPathRequest, SavedPathResponse
from app.services.skill_path_service import (
    SkillPathService,
    get_saved_skill_path,
    save_skill_path,
)

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillPathResponse(BaseModel):
    motivation: str | None
    slugs: list[str]


@router.get("/path", response_model=SkillPathResponse)
async def get_my_skill_path(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SkillPathResponse:
    goal = (
        await db.execute(select(GoalContract).where(GoalContract.user_id == current_user.id))
    ).scalar_one_or_none()
    motivation = goal.motivation if goal else None
    service = SkillPathService(db)
    slugs = await service.compute_path_slugs(motivation)
    return SkillPathResponse(motivation=motivation, slugs=slugs)


@router.post("/me/path", status_code=204)
async def save_my_path(
    body: SavedPathRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await save_skill_path(db, user_id=current_user.id, skill_ids=body.skill_ids)


@router.get("/me/path", response_model=SavedPathResponse | None)
async def get_my_saved_path(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedPathResponse | None:
    return await get_saved_skill_path(db, user_id=current_user.id)
