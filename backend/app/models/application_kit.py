"""ApplicationKit — bundled "ready to apply" assets snapshot.

A kit is the conversion artifact at the bottom of Job Readiness. It
references (with set-null fallbacks) the resume, tailored variant, JD,
mock interview report, and autopsy that powered it; the manifest captures
the resolved snapshots so the kit is reproducible even after the source
rows mutate.

Status lifecycle: building → ready → failed. PDF lands in `pdf_blob` on
ready; absent on building/failed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApplicationKit(Base):
    __tablename__ = "application_kits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    target_role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tailored_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tailored_resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    jd_library_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jd_library.id", ondelete="SET NULL"),
        nullable=True,
    )
    mock_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    autopsy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portfolio_autopsy_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Snapshot dict — resolved copies of the source rows captured at build.
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # building | ready | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="building"
    )
    pdf_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
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
