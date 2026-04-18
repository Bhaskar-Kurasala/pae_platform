import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class Reflection(Base, UUIDMixin, TimestampMixin):
    """One reflection per user per calendar day.

    Uniqueness is on (user_id, reflection_date) — the upsert route overwrites
    the row if the user re-submits the same day.
    """

    __tablename__ = "reflections"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "reflection_date", name="uq_reflections_user_date"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reflection_date: Mapped[date] = mapped_column(Date, nullable=False)
    mood: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # P3 3A-12: `day_end` for the evening "how did today go?" card, the
    # default and only value today. Left as a plain string so we can
    # add `self_explanation` or `mid_session` later without an enum
    # migration.
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="day_end", server_default="day_end"
    )
