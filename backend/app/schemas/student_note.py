"""Schemas for admin student intervention notes (P3 3A-18)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StudentNoteCreate(BaseModel):
    body_md: str = Field(min_length=1, max_length=4000)


class StudentNoteResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    admin_id: uuid.UUID
    student_id: uuid.UUID
    body_md: str
    created_at: datetime
