import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, get_current_user_optional
from app.models.course import Course
from app.models.user import User
from app.schemas.course import CourseCreate, CourseResponse, CourseUpdate
from app.services.course_service import CourseService

router = APIRouter(prefix="/courses", tags=["courses"])


def get_service(db: AsyncSession = Depends(get_db)) -> CourseService:
    return CourseService(db)


@router.get("", response_model=list[CourseResponse])
async def list_courses(
    service: CourseService = Depends(get_service),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[Course]:
    return await service.list_courses(current_user)


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: uuid.UUID,
    service: CourseService = Depends(get_service),
) -> Course:
    return await service.get_course(course_id)


@router.post("", response_model=CourseResponse, status_code=201)
async def create_course(
    payload: CourseCreate,
    service: CourseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> Course:
    return await service.create_course(payload, current_user)


@router.put("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: uuid.UUID,
    payload: CourseUpdate,
    service: CourseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> Course:
    return await service.update_course(course_id, payload, current_user)


@router.delete("/{course_id}", status_code=204)
async def delete_course(
    course_id: uuid.UUID,
    service: CourseService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> None:
    await service.delete_course(course_id, current_user)
