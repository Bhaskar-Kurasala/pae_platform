"""InterviewSession model — persisted mock interview sessions with per-answer rubric scores."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # behavioral | technical | system_design
    mode: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    # active | completed
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="active")
    # list of question strings asked during the session
    questions_asked: Mapped[list | None] = mapped_column(sa.JSON, nullable=True, default=list)
    # list of score dicts — one per submitted answer
    scores: Mapped[list | None] = mapped_column(sa.JSON, nullable=True, default=list)
    overall_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        onupdate=sa.func.now(),
        nullable=True,
    )
