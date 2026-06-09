"""StudentAssetProgress — per-(student, asset) granular completion.

The lesson-level `student_progress` row is the rollup; this table is the
source of truth that drives it. Mux webhook updates `watch_pct` and
`watched_seconds` for video assets; the notebook-execute endpoint stamps
`executed_at` + bumps `execution_count` for notebook assets.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin

ASSET_PROGRESS_NOT_STARTED = "not_started"
ASSET_PROGRESS_IN_PROGRESS = "in_progress"
ASSET_PROGRESS_COMPLETED = "completed"
ASSET_PROGRESS_STATUSES: frozenset[str] = frozenset(
    {
        ASSET_PROGRESS_NOT_STARTED,
        ASSET_PROGRESS_IN_PROGRESS,
        ASSET_PROGRESS_COMPLETED,
    }
)


class StudentAssetProgress(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "student_asset_progress"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "asset_id", name="uq_student_asset_progress_student_asset"
        ),
        CheckConstraint(
            "status IN ('not_started','in_progress','completed')",
            name="ck_student_asset_progress_status",
        ),
        CheckConstraint(
            "watch_pct >= 0 AND watch_pct <= 1",
            name="ck_student_asset_progress_watch_pct_range",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lesson_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ASSET_PROGRESS_NOT_STARTED, nullable=False
    )
    watch_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_position_seconds: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    watched_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
