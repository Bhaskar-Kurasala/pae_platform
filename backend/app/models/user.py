from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDMixin

# D-C (Batch 1): configurable lockout parameters with safe defaults.
_LOCKOUT_MAX_ATTEMPTS = 5
_LOCKOUT_DURATION_MINUTES = 15


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
    # Promotion gate — set once when the student crosses ALL four rungs.
    # Used to fire the takeover exactly once and to render "Promoted on …" copy.
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    promoted_to_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # D16/CP3.1 — manual-WhatsApp outreach destination. Free-form text
    # (E.164 hint in schemas/user.py); admin sources at signup or
    # backfills via /api/v1/admin/students/{id}/whatsapp_number. Empty
    # / NULL means no WhatsApp deep-link rendered on the cockpit panel.
    whatsapp_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    # D19.2 / CP1.4 — per-student daily cost ceiling override.
    # NULL → use the tier-based default from STUDENT_DAILY_COST_CEILING_INR
    # env var (free tier) or the paid-tier course config.
    # Non-NULL → use this value as the ceiling for this user, regardless
    # of tier. Wins over tier defaults; primarily for tightening
    # individual students (suspected adversarial use, budget concerns)
    # or loosening (paying customer with a one-off allowance) without
    # changing the global tier configuration.
    daily_cost_ceiling_inr_override: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )
    # Batch 1 / D-C — account lockout columns (added in migration 0069).
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Lockout helper methods (D-C) ──────────────────────────────────

    def is_locked(self) -> bool:
        """Return True if the account is currently locked."""
        if self.locked_until is None:
            return False
        return datetime.now(UTC) < self.locked_until

    def locked_seconds_remaining(self) -> int:
        """Return seconds until lockout expires, rounded up. 0 if not locked."""
        if not self.is_locked() or self.locked_until is None:
            return 0
        delta = self.locked_until - datetime.now(UTC)
        return max(0, int(delta.total_seconds()) + 1)

    def record_failed_login(self) -> None:
        """Increment failed_login_count; extend lockout if threshold reached.

        Sliding window: a failed attempt while already locked pushes
        locked_until forward by another _LOCKOUT_DURATION_MINUTES.
        """
        self.failed_login_count += 1
        if self.failed_login_count >= _LOCKOUT_MAX_ATTEMPTS:
            self.locked_until = datetime.now(UTC) + timedelta(minutes=_LOCKOUT_DURATION_MINUTES)

    def record_successful_login(self) -> None:
        """Reset lockout state on a successful credential check."""
        self.failed_login_count = 0
        self.locked_until = None

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student", lazy="select")
    submissions: Mapped[list["ExerciseSubmission"]] = relationship(
        back_populates="student", lazy="select"
    )
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", lazy="select")
    payments: Mapped[list["Payment"]] = relationship(back_populates="user", lazy="select")


from app.models.enrollment import Enrollment  # noqa: E402
from app.models.exercise_submission import ExerciseSubmission  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.payment import Payment  # noqa: E402
