import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDMixin


class Exercise(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "exercises"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    exercise_type: Mapped[str] = mapped_column(String(50), default="coding", nullable=False)
    difficulty: Mapped[str] = mapped_column(String(50), default="medium", nullable=False)
    starter_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    solution_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_cases: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rubric: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    github_template_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    lesson: Mapped["Lesson"] = relationship(back_populates="exercises")
    submissions: Mapped[list["ExerciseSubmission"]] = relationship(
        back_populates="exercise", lazy="select"
    )


from app.models.exercise_submission import ExerciseSubmission  # noqa: E402
from app.models.lesson import Lesson  # noqa: E402
