"""Mock interview v3 — questions, answers, reports, weakness ledger, cost log.

These models drive the sub-agent architecture (QuestionSelector / Interviewer /
Scorer / Analyst). The legacy InterviewSession keeps its `questions_asked` and
`scores` JSON columns intact for backwards compatibility — v3 writes to the
new structured tables instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MockQuestion(Base):
    __tablename__ = "mock_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    mode: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    # 0.0 = warm-up, 1.0 = hardest. QuestionSelector floats this with rolling
    # rubric overall.
    difficulty: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.5, server_default="0.5"
    )
    # generated | library | adaptive_followup
    source: Mapped[str] = mapped_column(
        sa.String(40), nullable=False, default="generated", server_default="generated"
    )
    parent_question_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("mock_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    rubric: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    # 1-indexed ordinal within the session
    position: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class MockAnswer(Base):
    __tablename__ = "mock_answers"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("mock_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    audio_ref: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    # Full Scorer JSON: {scores: {...}, overall: float, confidence: float,
    # feedback: str, follow_up: str | None, would_pass: bool}
    evaluation: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    filler_word_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    time_to_first_word_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    word_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class MockSessionReport(Base):
    __tablename__ = "mock_session_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    rubric_summary: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    patterns: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    strengths: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    weaknesses: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    next_action: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    headline: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # would_pass | borderline | would_not_pass | needs_human_review
    verdict: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    analyst_confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class MockWeaknessLedger(Base):
    """Per-student rolling record of weaknesses to revisit in future sessions."""

    __tablename__ = "mock_weakness_ledger"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "concept", name="ix_mock_weakness_ledger_user_concept"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Skill / concept slug. e.g. "hashing", "system_design.scaling", "behavioral.star_result"
    concept: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    # 0.0 = mild, 1.0 = severe blocker
    severity: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.5, server_default="0.5"
    )
    # List of UUIDs of sessions where this surfaced
    evidence_session_ids: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    addressed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class MockCostLog(Base):
    __tablename__ = "mock_cost_log"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # question_selector | interviewer | scorer | analyst
    sub_agent: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    model: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    input_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    cost_inr: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.0, server_default="0.0"
    )
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
