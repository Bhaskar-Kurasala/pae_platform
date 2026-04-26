"""CourseEntitlement — authoritative "user has access to this course".

Sits on top of `enrollments` (which mixes free/paid signals + progress).
Lesson-access middleware reads THIS table, not `enrollments`.

Source field captures *why* the entitlement was granted:
  purchase     — paid order
  free         — free course auto-granted at signup or on first click
  bundle       — granted as part of a multi-course bundle order
  admin_grant  — manually granted by an admin (comp, beta, etc.)
  trial        — time-limited preview; uses expires_at

Partial unique index (user_id, course_id) WHERE revoked_at IS NULL means
at most ONE active entitlement per (user, course). Revoked rows are kept
for audit; a re-grant inserts a fresh row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ENTITLEMENT_SOURCE_PURCHASE = "purchase"
ENTITLEMENT_SOURCE_FREE = "free"
ENTITLEMENT_SOURCE_BUNDLE = "bundle"
ENTITLEMENT_SOURCE_ADMIN_GRANT = "admin_grant"
ENTITLEMENT_SOURCE_TRIAL = "trial"

ENTITLEMENT_SOURCES = {
    ENTITLEMENT_SOURCE_PURCHASE,
    ENTITLEMENT_SOURCE_FREE,
    ENTITLEMENT_SOURCE_BUNDLE,
    ENTITLEMENT_SOURCE_ADMIN_GRANT,
    ENTITLEMENT_SOURCE_TRIAL,
}


class CourseEntitlement(Base):
    __tablename__ = "course_entitlements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # Foreign key in spirit (orders.id, course_bundles.id, ...) but kept
    # type-agnostic so the same column points at different tables based on
    # `source`. Nullable for free + admin_grant where there is no source row.
    source_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
