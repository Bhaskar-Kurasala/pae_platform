from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDMixin


class Course(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "courses"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(default=False, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(50), default="beginner", nullable=False)
    estimated_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    github_repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="course", lazy="select", order_by="Lesson.order"
    )
    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="course", lazy="select"
    )


from app.models.enrollment import Enrollment  # noqa: E402
from app.models.lesson import Lesson  # noqa: E402
