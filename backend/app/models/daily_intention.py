import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class DailyIntention(Base, UUIDMixin, TimestampMixin):
    """A one-line "what do you want to do today" (P3 3A-11).

    One row per (user, date). Resetting the intention later in the
    same day overwrites the row; the next calendar day gets a fresh
    prompt. The uniqueness constraint is what enforces the "fresh
    each day" contract — don't soften it without also teaching the
    UI to pick the newest row.
    """

    __tablename__ = "daily_intentions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "intention_date", name="uq_daily_intentions_user_date"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intention_date: Mapped[date] = mapped_column(Date, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
