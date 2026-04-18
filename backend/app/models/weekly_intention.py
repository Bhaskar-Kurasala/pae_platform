"""Weekly intentions (P3 3B #151).

Student sets 1-3 focus items for the week (text). One row per
(user_id, week_starting). Distinct from `daily_intentions` (which is
per-day).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class WeeklyIntention(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "weekly_intentions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "week_starting",
            "slot",
            name="uq_weekly_intentions_user_week_slot",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Monday of the target week (UTC).
    week_starting: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    # 1, 2, or 3 — the ordinal of this focus item in the trio.
    slot: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(String(280), nullable=False)
