import uuid
from datetime import datetime

from pydantic import BaseModel


class LessonProgressItem(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    order: int
    status: str  # "completed", "in_progress", "not_started"


class CourseProgress(BaseModel):
    course_id: uuid.UUID
    course_title: str
    total_lessons: int
    completed_lessons: int
    progress_percentage: float
    next_lesson_id: uuid.UUID | None
    next_lesson_title: str | None
    lessons: list[LessonProgressItem]


class ProgressResponse(BaseModel):
    courses: list[CourseProgress]
    overall_progress: float


# Legacy flat schema used by complete_lesson endpoint
class LessonProgressRecord(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    student_id: uuid.UUID
    lesson_id: uuid.UUID
    status: str
    watch_time_seconds: int
    completed_at: datetime | None = None
    last_position_seconds: int
    created_at: datetime
    updated_at: datetime
