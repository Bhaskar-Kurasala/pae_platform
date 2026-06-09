"""Spaced-repetition card (P2-05).

Persistent SM-2 state per (user, concept). Concepts are identified by a free-form
`concept_key` string so we don't need skills rows for every card (exercises and
lessons create cards too).

One row per (user_id, concept_key). Reviews update ease/interval/next_due_at
in place — history lives in agent_actions for audit.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class SRSCard(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "srs_cards"
    __table_args__ = (
        UniqueConstraint("user_id", "concept_key", name="uq_srs_cards_user_concept"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    concept_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ease_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
