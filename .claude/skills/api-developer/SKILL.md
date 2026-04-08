---
name: api-developer
description: |
  Use when building FastAPI routes, services, repositories, or schemas.
  Covers the route → service → repository → model pattern,
  Pydantic validation, async database access, and OpenAPI docs.
  Trigger phrases: "API endpoint", "route", "service", "backend"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, TodoWrite
---

# API Development Skill

## Pattern: Route → Service → Repository → Model

### Route (thin controller)
```python
# backend/app/api/v1/routes/courses.py
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.course import CourseResponse, CourseCreate
from app.services.course_service import CourseService
from app.core.security import get_current_user

router = APIRouter(prefix="/courses", tags=["courses"])

@router.get("/", response_model=list[CourseResponse])
async def list_courses(
    service: CourseService = Depends(),
    skip: int = 0, limit: int = 20,
):
    return await service.list_published(skip=skip, limit=limit)

@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    data: CourseCreate,
    service: CourseService = Depends(),
    user = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return await service.create(data)
```

### Service (business logic)
```python
# backend/app/services/course_service.py
from app.repositories.course_repo import CourseRepository
from app.schemas.course import CourseCreate

class CourseService:
    def __init__(self, repo: CourseRepository = Depends()):
        self.repo = repo
    
    async def list_published(self, skip: int = 0, limit: int = 20):
        return await self.repo.find_published(skip=skip, limit=limit)
    
    async def create(self, data: CourseCreate):
        return await self.repo.create(data.model_dump())
```

### Repository (database access)
```python
# backend/app/repositories/course_repo.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.course import Course

class CourseRepository:
    def __init__(self, session: AsyncSession = Depends(get_db)):
        self.session = session
    
    async def find_published(self, skip: int, limit: int) -> list[Course]:
        stmt = select(Course).where(Course.is_published == True).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

## Checklist for New Endpoint
- [ ] Pydantic schema (request + response) in `schemas/`
- [ ] Route in `api/v1/routes/` with proper HTTP method and status code
- [ ] Service method with business logic
- [ ] Repository method with async DB query
- [ ] Test in `tests/test_api/` using httpx TestClient
- [ ] Auth/permission check if needed
- [ ] OpenAPI docs auto-generated (verify at /docs)
