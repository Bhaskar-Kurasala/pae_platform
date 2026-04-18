"""Post-lesson retrieval quiz schemas (P3 3A-10)."""

import uuid
from typing import Any

from pydantic import BaseModel, Field


class RetrievalQuestion(BaseModel):
    """One MCQ handed to the client. `correct_answer` is intentionally
    omitted so the client can't peek before grading.
    """

    id: uuid.UUID
    question: str
    options: dict[str, Any]


class RetrievalQuizResponse(BaseModel):
    """Shape returned alongside a lesson completion."""

    questions: list[RetrievalQuestion]


class RetrievalQuizSubmission(BaseModel):
    """Student's answer map: mcq_id → chosen option key (e.g., "A")."""

    answers: dict[uuid.UUID, str] = Field(default_factory=dict)


class GradedQuestion(BaseModel):
    mcq_id: uuid.UUID
    correct: bool
    correct_answer: str
    explanation: str | None = None


class RetrievalQuizResult(BaseModel):
    correct: int
    total: int
    graded: list[GradedQuestion]
