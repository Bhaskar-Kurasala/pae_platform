import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class StudentMisconception(Base, UUIDMixin, TimestampMixin):
    """A student's factual error captured when the tutor disagreed.

    One row per disagreement turn — we deliberately do not deduplicate. A
    student repeating the same wrong claim later is signal, not noise. The
    row is written after the tutor response streams to completion, so a
    broken stream never leaves a half-logged entry.

    `topic` is best-effort (free text extracted from context or the
    assertion), not a foreign key, because the same factual error can span
    skills and we don't want a misclassified skill row to block the log.
    """

    __tablename__ = "student_misconceptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    student_assertion: Mapped[str] = mapped_column(Text, nullable=False)
    tutor_correction: Mapped[str] = mapped_column(Text, nullable=False)
