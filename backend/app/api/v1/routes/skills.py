import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.skill import (
    SkillEdgeResponse,
    SkillGraphResponse,
    SkillNode,
    UserSkillStateResponse,
    UserSkillTouchResponse,
)
from app.services.skill_service import SkillService

router = APIRouter(prefix="/skills", tags=["skills"])


def get_service(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(db)


@router.get("/graph", response_model=SkillGraphResponse)
async def get_skill_graph(
    service: SkillService = Depends(get_service),
) -> SkillGraphResponse:
    skills, edges = await service.list_graph()
    return SkillGraphResponse(
        nodes=[SkillNode.model_validate(s) for s in skills],
        edges=[SkillEdgeResponse.model_validate(e) for e in edges],
    )


@router.get("/me", response_model=list[UserSkillStateResponse])
async def get_my_skill_states(
    service: SkillService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> list[UserSkillStateResponse]:
    rows = await service.list_user_states(current_user)
    return [UserSkillStateResponse.model_validate(r) for r in rows]


@router.post(
    "/{skill_id}/touch",
    response_model=UserSkillTouchResponse,
    status_code=status.HTTP_200_OK,
)
async def touch_skill(
    skill_id: uuid.UUID,
    service: SkillService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> UserSkillTouchResponse:
    state = await service.touch(current_user, skill_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found"
        )
    assert state.last_touched_at is not None
    return UserSkillTouchResponse(
        skill_id=state.skill_id, last_touched_at=state.last_touched_at
    )
