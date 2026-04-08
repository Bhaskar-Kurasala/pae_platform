from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="student", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    github_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student", lazy="select")
    submissions: Mapped[list["ExerciseSubmission"]] = relationship(
        back_populates="student", lazy="select"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", lazy="select"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="user", lazy="select")


from app.models.enrollment import Enrollment  # noqa: E402
from app.models.exercise_submission import ExerciseSubmission  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.payment import Payment  # noqa: E402
