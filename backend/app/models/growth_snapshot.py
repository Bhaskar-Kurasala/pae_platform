"""Weekly per-user growth snapshot (P1-C-2).

Captures a frozen view of a student's learning state for one week so Receipts
and the weekly instructor letter can compare week-over-week without reading
the full event history each time.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class GrowthSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "growth_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "week_ending", name="uq_growth_snapshots_user_week"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Sunday 00:00 UTC of the week the snapshot covers.
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    lessons_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skills_touched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_concept: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Free-form payload: quiz scores, reflections count, exercise submissions,
    # motivation slug, whatever a future surface wants to render.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
