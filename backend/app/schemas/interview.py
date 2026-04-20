"""Pydantic schemas for the Interview Prep v2 endpoints (sessions + story bank)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class StartSessionRequest(BaseModel):
    """Request body for POST /interview/sessions/start."""

    mode: str = Field(..., pattern="^(behavioral|technical|system_design)$")
    topic: str | None = Field(None, description="Optional focus topic for the opening question")


class AnswerSubmitRequest(BaseModel):
    """Request body for POST /interview/sessions/answer."""

    session_id: uuid.UUID
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1, max_length=10_000)


class RubricScores(BaseModel):
    """Per-dimension rubric scores (0-10 each)."""

    clarity: int = Field(..., ge=0, le=10)
    structure: int = Field(..., ge=0, le=10)
    depth: int = Field(..., ge=0, le=10)
    evidence: int = Field(..., ge=0, le=10)
    confidence_language: int = Field(..., ge=0, le=10)


class AnswerEvaluation(BaseModel):
    """Full evaluation returned after an answer is submitted."""

    scores: RubricScores
    overall: float = Field(..., ge=0.0, le=10.0)
    feedback: str
    next_question: str
    tip: str


class SessionResponse(BaseModel):
    """Response after starting a new session."""

    id: uuid.UUID
    mode: str
    status: str
    first_question: str
    overall_score: float | None = None


class SessionListItem(BaseModel):
    """Lightweight session item for list responses."""

    id: uuid.UUID
    mode: str
    status: str
    overall_score: float | None = None
    questions_count: int


# ── Story Bank ────────────────────────────────────────────────────────────────

class StoryBankCreateRequest(BaseModel):
    """Request body for POST /interview/stories."""

    title: str = Field(..., min_length=1, max_length=255)
    situation: str = Field(..., min_length=1)
    task: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    result: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


class StoryBankItem(BaseModel):
    """Full story bank entry returned to the client."""

    id: uuid.UUID
    title: str
    situation: str
    task: str
    action: str
    result: str
    tags: list[str]

    model_config = {"from_attributes": True}
