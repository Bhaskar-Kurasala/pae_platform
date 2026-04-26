import uuid
from typing import Literal

from pydantic import BaseModel

ResourceKind = Literal["notebook", "repo", "video", "pdf", "slides", "link"]


class LessonResourceResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    lesson_id: uuid.UUID | None
    kind: ResourceKind
    title: str
    description: str | None
    order: int
    is_required: bool
    metadata: dict | None = None
    locked: bool = False  # True when student must enroll to open this resource

    class Config:
        from_attributes = True


class ResourceOpenResponse(BaseModel):
    """Returned by POST /resources/{id}/open — the URL the UI should redirect to."""

    kind: ResourceKind
    open_url: str
    expires_at: str | None = None  # ISO timestamp; None for non-expiring URLs
