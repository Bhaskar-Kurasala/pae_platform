"""F1 — StudentRiskSignals: nightly-computed slip pattern + risk score per user.

One row per user, upserted by the nightly scoring task. Read by:
  - F4 admin console panels (filter by slip_type, order by risk_score)
  - F9 nightly automation (skip recently-contacted users)

The seven slip_types match docs/RETENTION-ENGINE.md:
  none | cold_signup | unpaid_stalled | streak_broken |
  paid_silent | capstone_stalled | promotion_avoidant
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class StudentRiskSignals(Base, UUIDMixin):
    __tablename__ = "student_risk_signals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    slip_type: Mapped[str] = mapped_column(String(64), nullable=False)
    days_since_last_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_streak_ever: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recommended_intervention: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    risk_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
