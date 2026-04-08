import uuid
from datetime import datetime

from pydantic import BaseModel


class CourseCreate(BaseModel):
    title: str
    slug: str
    description: str | None = None
    thumbnail_url: str | None = None
    price_cents: int = 0
    difficulty: str = "beginner"
    estimated_hours: int = 0
    github_repo_url: str | None = None


class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    price_cents: int | None = None
    is_published: bool | None = None
    difficulty: str | None = None
    estimated_hours: int | None = None


class CourseResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    slug: str
    description: str | None = None
    thumbnail_url: str | None = None
    price_cents: int
    is_published: bool
    difficulty: str
    estimated_hours: int
    created_at: datetime
    updated_at: datetime
