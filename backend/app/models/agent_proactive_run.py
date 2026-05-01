"""ORM model for `agent_proactive_runs` (Agentic OS — Primitive 5).

Audit row for every cron-fired or webhook-fired agent execution.
Idempotency is critical here:

  • Cron: Celery task can fire twice on a worker restart. The
    application builds idempotency_key as
    f"{agent}:{cron_expr}:{date_bucket}" so a second fire on the
    same day collapses to one row.
  • Webhook: GitHub redelivers events freely. We use the provider's
    delivery ID (X-GitHub-Delivery, Stripe event.id) so a retry
    storm doesn't multiply runs.

NULL idempotency_key skips the unique guard — fine for one-off
manual triggers, never use NULL from automated callers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class AgentProactiveRun(Base, UUIDMixin):
    __tablename__ = "agent_proactive_runs"

    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    # 'cron' | 'webhook:github' | 'webhook:stripe' | 'webhook:custom'
    trigger_source: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_key: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','ok','error','skipped')",
            name="agent_proactive_runs_status_chk",
        ),
    )
