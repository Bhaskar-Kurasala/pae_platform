"""Pydantic schemas for the Mock Interview v3 API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Modes available in MVP. system_design is reserved for Phase 2.
MockMode = Literal["behavioral", "technical_conceptual", "live_coding", "system_design"]
LevelLiteral = Literal["junior", "mid", "senior"]


class StartMockRequest(BaseModel):
    """POST /api/v1/mock/sessions/start"""

    mode: MockMode
    target_role: str = Field(..., min_length=1, max_length=255)
    level: LevelLiteral = "junior"
    jd_text: str | None = Field(default=None, max_length=10_000)
    voice_enabled: bool = False


class MockQuestionPayload(BaseModel):
    id: uuid.UUID
    text: str
    mode: str
    difficulty: float = Field(..., ge=0.0, le=1.0)
    source: str
    position: int


class StartMockResponse(BaseModel):
    session_id: uuid.UUID
    mode: MockMode
    target_role: str
    level: LevelLiteral
    voice_enabled: bool
    first_question: MockQuestionPayload
    memory_recall: str | None = Field(
        default=None,
        description="Conversational greeting referencing prior weaknesses, if any.",
    )


class SubmitAnswerRequest(BaseModel):
    """POST /api/v1/mock/sessions/{session_id}/answer"""

    question_id: uuid.UUID
    text: str = Field(..., min_length=1, max_length=10_000)
    audio_ref: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    time_to_first_word_ms: int | None = Field(default=None, ge=0)


class RubricCriterion(BaseModel):
    name: str
    score: int = Field(..., ge=0, le=10)
    rationale: str


class AnswerEvaluation(BaseModel):
    """Per-answer evaluation surfaced to the client. Honors confidence threshold."""

    criteria: list[RubricCriterion]
    overall: float = Field(..., ge=0.0, le=10.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    would_pass: bool
    feedback: str
    needs_human_review: bool = Field(
        default=False,
        description="True when confidence < 0.6. Client must hide numeric scores when set.",
    )


class SubmitAnswerResponse(BaseModel):
    answer_id: uuid.UUID
    evaluation: AnswerEvaluation
    next_question: MockQuestionPayload | None = None
    interviewer_reaction: str | None = Field(
        default=None,
        description="Short conversational follow-up from the Interviewer sub-agent.",
    )
    cost_inr_so_far: float
    cost_cap_exceeded: bool = False


class MockTranscriptTurn(BaseModel):
    role: Literal["interviewer", "candidate"]
    text: str
    at: datetime
    audio_ref: str | None = None


class PatternInsights(BaseModel):
    filler_word_rate: float = Field(..., description="filler words per 100 words")
    avg_time_to_first_word_ms: float | None
    avg_words_per_answer: float
    evasion_count: int
    confidence_language_score: float = Field(..., ge=0.0, le=10.0)


class NextAction(BaseModel):
    label: str
    detail: str
    target_url: str | None = None


class SessionReportResponse(BaseModel):
    session_id: uuid.UUID
    headline: str
    verdict: str
    rubric_summary: dict[str, float]
    patterns: PatternInsights
    strengths: list[str]
    weaknesses: list[str]
    next_action: NextAction
    analyst_confidence: float = Field(..., ge=0.0, le=1.0)
    needs_human_review: bool
    transcript: list[MockTranscriptTurn]
    total_cost_inr: float
    share_token: str | None = None


class CompleteSessionResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    report: SessionReportResponse


class MockSessionListItem(BaseModel):
    id: uuid.UUID
    mode: str
    target_role: str | None
    status: str
    overall_score: float | None
    total_cost_inr: float
    created_at: datetime


class ShareResponse(BaseModel):
    share_token: str
    public_url: str
