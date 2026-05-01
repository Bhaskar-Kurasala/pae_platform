"""ORM model for `student_inbox` (Agentic OS — Primitive 5).

The destination for proactive output. Cards land here, the frontend
reads "WHERE user_id = $1 AND read_at IS NULL", and the in-app
inbox renders them.

`kind` classifies the card (used for icon + grouping in the UI):
  nudge          — re-engagement copy from disrupt_prevention
  celebration    — milestone copy from community_celebrator
  job_brief      — weekly job match summary
  review_due     — spaced-repetition prompts
  insight        — general "we noticed X" notes
  …add as needed

Idempotency is per-user, scoped by the originating agent's key
construction. Nudge for "Priya, day-3 silent" gets the same key
across retries; the partial unique index throws on collision and
the app catches → no-op.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class StudentInbox(Base, UUIDMixin):
    __tablename__ = "student_inbox"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    cta_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Renamed to `metadata_` in Python because SQLAlchemy reserves
    # `metadata` on the declarative base. Column name in the DB stays
    # `metadata` for query ergonomics.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=func.cast("{}", JSONB),
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
