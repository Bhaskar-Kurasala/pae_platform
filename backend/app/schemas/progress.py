import uuid
from datetime import datetime

from pydantic import BaseModel


class ProgressResponse(BaseModel):
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
