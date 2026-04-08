import uuid
from datetime import datetime

from pydantic import BaseModel


class EnrollmentCreate(BaseModel):
    student_id: uuid.UUID
    course_id: uuid.UUID
    payment_id: uuid.UUID | None = None


class EnrollmentResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    student_id: uuid.UUID
    course_id: uuid.UUID
    status: str
    enrolled_at: datetime
    completed_at: datetime | None = None
    progress_pct: float
    created_at: datetime
