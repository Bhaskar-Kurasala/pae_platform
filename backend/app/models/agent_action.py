import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class AgentAction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agent_actions"

    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="completed", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(nullable=True)

    # DISC-57 — actor identity so admin-triggered runs are distinguishable.
    # `actor_role` is denormalized on purpose: it survives a future role change
    # on the user row, giving compliance a point-in-time attribution.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    on_behalf_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    student: Mapped["User | None"] = relationship(
        lazy="select", foreign_keys=[student_id]
    )


from app.models.user import User  # noqa: E402
