import uuid
from datetime import datetime

from pydantic import BaseModel


class LessonCreate(BaseModel):
    course_id: uuid.UUID
    title: str
    slug: str
    description: str | None = None
    content: str | None = None
    video_url: str | None = None
    youtube_video_id: str | None = None
    duration_seconds: int = 0
    order: int = 0
    is_free_preview: bool = False
    github_branch: str | None = None
    skill_id: uuid.UUID | None = None


class LessonUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    content: str | None = None
    video_url: str | None = None
    duration_seconds: int | None = None
    order: int | None = None
    is_published: bool | None = None
    is_free_preview: bool | None = None
    skill_id: uuid.UUID | None = None


class LessonResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    slug: str
    description: str | None = None
    duration_seconds: int
    order: int
    is_published: bool
    is_free_preview: bool
    skill_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
