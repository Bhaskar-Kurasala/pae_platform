"""SQLAlchemy models backing the v1 Admin Console (CareerForge_admin_v1).

Eight tables holding student profile/risk extensions, engagement rollups,
funnel/pulse/feature snapshots, the live event feed, scheduled calls and
top-card risk narratives.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class AdminConsoleProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "admin_console_profiles"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    track: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_label: Mapped[str] = mapped_column(String(32), nullable=False)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AdminConsoleEngagement(Base, UUIDMixin):
    __tablename__ = "admin_console_engagement"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    sessions_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flashcards_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_questions_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviews_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    labs_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capstones_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    purchases_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class AdminConsoleFunnelSnapshot(Base, UUIDMixin):
    __tablename__ = "admin_console_funnel_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    signups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    onboarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_lesson: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capstone: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    promoted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class AdminConsolePulseMetric(Base, UUIDMixin):
    __tablename__ = "admin_console_pulse_metrics"

    metric_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    display_value: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    delta_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delta_text: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    color_hex: Mapped[str] = mapped_column(String(16), nullable=False, default="#5fa37f")
    invert_delta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    spark: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class AdminConsoleFeatureUsage(Base, UUIDMixin):
    __tablename__ = "admin_console_feature_usage"

    feature_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    count_label: Mapped[str] = mapped_column(String(32), nullable=False)
    sub_label: Mapped[str] = mapped_column(String(64), nullable=False)
    is_cold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bars: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class AdminConsoleEvent(Base, UUIDMixin):
    __tablename__ = "admin_console_events"

    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class AdminConsoleCall(Base, UUIDMixin):
    __tablename__ = "admin_console_calls"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    display_time: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class AdminConsoleRiskReason(Base, UUIDMixin):
    __tablename__ = "admin_console_risk_reasons"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
