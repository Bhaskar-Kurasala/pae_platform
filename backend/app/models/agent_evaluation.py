"""ORM model for `agent_evaluations` (Agentic OS — Primitive 4).

Every critic run lands here, attempt-by-attempt. The same execute()
can produce multiple rows (attempt 1 fails → retry attempt 2). The
prompt-quality dashboard reads `WHERE passed=false GROUP BY agent_name
ORDER BY count DESC` to spot agents that need attention.

Three sub-scores (accuracy / helpful / complete) are nullable because
some agents only make sense to score on one or two dimensions.
`total_score` is always present and is the single number used for the
threshold check.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class AgentEvaluation(Base, UUIDMixin):
    __tablename__ = "agent_evaluations"

    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    call_chain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    accuracy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    helpful_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    complete_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    critic_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # D17b/ITEM 4.A — explicit failure-class discriminator. Mirrors
    # EvalFailureClass in app/agents/primitives/evaluation.py. Nullable
    # for backfill compatibility (pre-D17b rows have no signal); new
    # writes always supply a value via _write_evaluation_row's required
    # parameter. CHECK constraint at the DB layer enforces the enum
    # (see migration 0066_eval_failure_class).
    failure_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "total_score BETWEEN 0.0 AND 1.0",
            name="agent_evaluations_total_range",
        ),
        CheckConstraint(
            "attempt_number >= 1", name="agent_evaluations_attempt_pos"
        ),
        # The failure_class enum CHECK is added in migration 0066 with
        # the same name; declared here for SQLAlchemy metadata parity
        # so model-driven schema validation matches the migrated DB.
        CheckConstraint(
            "failure_class IS NULL OR failure_class IN "
            "('none', 'below_threshold', 'critic_flaked', 'agent_raised')",
            name="agent_evaluations_failure_class_enum",
        ),
    )
