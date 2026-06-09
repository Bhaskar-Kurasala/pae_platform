"""CourseBundle — multi-course package SKU.

A bundle is a real catalog object that wraps N course_ids into one SKU.
Buying a bundle creates one Order whose `target_type="bundle"` and
`target_id=<bundle.id>`; on fulfillment, N entitlements are granted with
`source="bundle"` and `source_ref=<order.id>`.

This replaces the hard-coded bundle cards in the catalog UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CourseBundle(Base):
    __tablename__ = "course_bundles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(120), unique=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="INR"
    )
    # JSON list of course UUIDs (as strings) — keeps the bundle composition
    # snapshotted at sale time even if a course is later removed.
    course_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
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
