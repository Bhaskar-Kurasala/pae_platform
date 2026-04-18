import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ExerciseSubmission(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "exercise_submissions"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # P2-07: opt-in gallery. Only explicitly-shared submissions surface to peers.
    shared_with_peers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # P2-07: author annotation — what the student wants peers to notice.
    share_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # P3 3A-9: "why does your approach work?" captured pre-grade to force
    # metacognition. Nullable so legacy rows and UI-less API callers still
    # flow through.
    self_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped["User"] = relationship(back_populates="submissions")
    exercise: Mapped["Exercise"] = relationship(back_populates="submissions")


from app.models.exercise import Exercise  # noqa: E402
from app.models.user import User  # noqa: E402
