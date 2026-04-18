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
