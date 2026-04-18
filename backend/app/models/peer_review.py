"""Peer review exchange (P3 3B #101).

When a student shares a submission with peers, we assign N reviewers
from the eligible pool. Each reviewer fills in a structured review
(1-5 rating + optional comment). Assignment and review co-live on the
same row — `completed_at` is the signal that the review is filled in.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class PeerReviewAssignment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "peer_review_assignments"
    __table_args__ = (
        UniqueConstraint(
            "submission_id",
            "reviewer_id",
            name="uq_peer_review_submission_reviewer",
        ),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercise_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 1..5 once completed, null while pending.
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
