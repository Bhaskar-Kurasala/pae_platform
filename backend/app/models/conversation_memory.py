import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ConversationMemory(Base, UUIDMixin, TimestampMixin):
    """Per-(user, skill) rolling summary of what was covered.

    One row per user/skill pair. The upsert path in the memory service
    overwrites `summary_text` and `last_updated` when new material is
    discussed. Surfaced to the tutor at session-open so continuity costs
    less than a re-introduction.
    """

    __tablename__ = "conversation_memory"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "skill_id", name="uq_conversation_memory_user_skill"
        ),
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
    summary_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
