"""LearningSession — per-user "Session N" record for the Today screen.

Replaces the hardcoded `Session 14` chip with a real ordinal computed per
user. A new session opens whenever the user lands on Today after a gap >
SESSION_GAP_MINUTES; the three step timestamps (warmup/lesson/reflect) feed
the session-flow card on Today and the rail "What unlocks next" timeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class LearningSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "learning_sessions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "ordinal", name="uq_learning_sessions_user_ordinal"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    warmup_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lesson_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reflect_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
