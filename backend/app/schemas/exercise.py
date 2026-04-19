import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ExerciseCreate(BaseModel):
    lesson_id: uuid.UUID
    title: str
    description: str | None = None
    exercise_type: str = "coding"
    difficulty: str = "medium"
    starter_code: str | None = None
    solution_code: str | None = None
    test_cases: dict[str, Any] | None = None
    rubric: dict[str, Any] | None = None
    points: int = 100
    order: int = 0
    skill_id: uuid.UUID | None = None


class ExerciseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    difficulty: str | None = None
    points: int | None = None
    order: int | None = None
    skill_id: uuid.UUID | None = None


class ExerciseResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    lesson_id: uuid.UUID
    title: str
    description: str | None = None
    exercise_type: str
    difficulty: str
    starter_code: str | None = None
    rubric: dict[str, Any] | None = None
    points: int
    order: int
    skill_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
