"""Resume model for career module (#168)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="My Resume", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # bullets: list of {text, evidence_id, ats_keywords} dicts (populated by Claude)
    bullets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    skills_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    linkedin_blurb: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Flat list of ATS-optimised keywords for the full resume
    ats_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # strong_fit | good_fit | needs_work — derived from average skill confidence
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Self-attested context captured during the tailored-resume intake flow.
    # Schema: {non_platform_experience: [...], education: [...], preferences: {...}}
    intake_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
