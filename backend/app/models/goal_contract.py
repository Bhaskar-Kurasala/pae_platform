import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class GoalContract(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "goal_contracts"
    __table_args__ = (UniqueConstraint("user_id", name="uq_goal_contracts_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    motivation: Mapped[str] = mapped_column(String(32), nullable=False)
    deadline_months: Mapped[int] = mapped_column(Integer, nullable=False)
    success_statement: Mapped[str] = mapped_column(Text, nullable=False)
