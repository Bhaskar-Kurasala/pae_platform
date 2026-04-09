import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SubmissionCreate(BaseModel):
    exercise_id: uuid.UUID | None = None
    code: str | None = None
    github_pr_url: str | None = None


class SubmissionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    student_id: uuid.UUID
    exercise_id: uuid.UUID
    status: str
    score: int | None = None
    feedback: str | None = None
    ai_feedback: dict[str, Any] | None = None
    attempt_number: int
    created_at: datetime
    updated_at: datetime
