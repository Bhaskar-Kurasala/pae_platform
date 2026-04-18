import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ConfidenceReport(Base, UUIDMixin, TimestampMixin):
    """A self-reported confidence value captured after a tutor exchange.

    Overconfidence is the strongest predictor of skill gaps — asking the
    student to rate themselves 1-5 after a session is the cheapest signal
    we can collect. `asked_at` records when the tutor surfaced the prompt;
    `answered_at` records when the student submitted. They differ so we can
    measure how often students answer vs. ignore.

    `skill_id` is nullable because a tutor session may not have a single
    skill in scope — we'd rather log the self-report with null skill than
    drop it on a missing attribution.
    """

    __tablename__ = "confidence_reports"
    __table_args__ = (
        CheckConstraint(
            "value >= 1 AND value <= 5",
            name="ck_confidence_reports_value_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    asked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
