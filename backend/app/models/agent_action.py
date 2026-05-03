import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
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

    # cost_inr per Pass 3f §D.2 — added in migration 0057_entitlement_tier.
    # The mv_student_daily_cost materialized view aggregates SUM(cost_inr)
    # per (student, day) for the cost-ceiling enforcement at Layer 3
    # of the entitlement model. Populated by:
    #   • legacy BaseAgent.log_action via state.metadata.{input,output}_tokens
    #     → estimate_cost_inr → telemetry only (NOT cost_inr column today)
    #   • AgenticBaseAgent.execute via _track_llm_usage accumulator
    #     → estimate_cost_inr → cost_inr column (D10 Checkpoint 3)
    # NUMERIC(12,4) so sub-rupee per-call costs (Haiku is ~₹0.20) aren't
    # lost to rounding.
    cost_inr: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=4), nullable=True
    )

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
