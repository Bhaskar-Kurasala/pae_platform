from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.reflection import ReflectionCreate, ReflectionResponse
from app.services.reflection_service import ReflectionService

router = APIRouter(prefix="/reflections", tags=["reflections"])


def get_service(db: AsyncSession = Depends(get_db)) -> ReflectionService:
    return ReflectionService(db)


@router.get("/me/today", response_model=ReflectionResponse | None)
async def get_my_reflection_today(
    service: ReflectionService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ReflectionResponse | None:
    """Returns today's reflection, or 204 if none logged yet.

    Returning None (with 200) rather than 404 so the frontend doesn't treat
    "not yet filled" as an error condition.
    """
    reflection = await service.get_today(current_user)
    if reflection is None:
        return None
    return ReflectionResponse.model_validate(reflection)


@router.get("/me/recent", response_model=list[ReflectionResponse])
async def list_my_recent_reflections(
    limit: int = 30,
    service: ReflectionService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> list[ReflectionResponse]:
    if limit < 1 or limit > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 365",
        )
    rows = await service.list_recent(current_user, limit=limit)
    return [ReflectionResponse.model_validate(r) for r in rows]


@router.post("/me", response_model=ReflectionResponse)
async def upsert_my_reflection(
    payload: ReflectionCreate,
    response: Response,
    service: ReflectionService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ReflectionResponse:
    reflection, created = await service.upsert(current_user, payload)
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return ReflectionResponse.model_validate(reflection)
