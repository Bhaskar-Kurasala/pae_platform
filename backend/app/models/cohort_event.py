"""CohortEvent — append-only feed driving the "Cohort, live" rail on Today.

Each row is a public-facing event from the cohort: someone leveled up, shipped
a capstone, started a streak, etc. `actor_handle` is the masked display name
(e.g. "Priya K."). `level_slug` lets us scope the cohort feed by promotion
level so users at Python Developer don't see Data Engineer events.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class CohortEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "cohort_events"

    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    actor_handle: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    level_slug: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
