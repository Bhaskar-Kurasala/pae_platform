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


class DailyCompletion(BaseModel):
    """Count of lesson completions bucketed by local calendar date (YYYY-MM-DD)."""

    date: str
    count: int


class ProgressResponse(BaseModel):
    courses: list[CourseProgress]
    overall_progress: float
    lessons_completed_total: int = 0
    lessons_total: int = 0
    exercises_completed: int = 0
    total_exercises: int = 0
    exercise_completion_rate: float = 0.0
    watch_time_minutes: int = 0
    completions_by_day: list[DailyCompletion] = []
    active_course_id: uuid.UUID | None = None
    active_course_title: str | None = None
    next_lesson_id: uuid.UUID | None = None
    next_lesson_title: str | None = None
    today_unlock_percentage: float = 0.0


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
