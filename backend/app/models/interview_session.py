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
    # behavioral | technical_conceptual | live_coding | system_design (legacy: technical)
    mode: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    # active | completed
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="active")
    # legacy: list of question strings asked during the session (mock v3 uses MockQuestion)
    questions_asked: Mapped[list | None] = mapped_column(sa.JSON, nullable=True, default=list)
    # legacy: list of score dicts — one per submitted answer (mock v3 uses MockAnswer)
    scores: Mapped[list | None] = mapped_column(sa.JSON, nullable=True, default=list)
    overall_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    # ── Mock interview v3 additions (migration 0038) ────────────────────
    target_role: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    level: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    jd_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    voice_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default="false"
    )
    total_cost_inr: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.0, server_default="0.0"
    )
    share_token: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    # BUG-CP1D fix (2026-05-09): live schema is NOT NULL DEFAULT now()
    # but the model previously declared nullable=True without
    # server_default. SQLAlchemy then INSERTed explicit NULL, overriding
    # the DB default — every mock interview start hit a 500 on the
    # NotNullViolationError. Aligning the ORM to schema:
    #   * nullable=False matches the schema constraint.
    #   * server_default=sa.func.now() means SA omits the column from
    #     INSERT when unset, letting the DB apply the default.
    #   * onupdate=sa.func.now() preserves the auto-touch on UPDATE.
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )
