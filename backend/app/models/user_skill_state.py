import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class UserSkillState(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "user_skill_states"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_user_skill_states_user_skill"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mastery_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_touched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
