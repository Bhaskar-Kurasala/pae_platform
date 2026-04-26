"""MigrationGate — durable state for in-flight data migrations.

Used by parallel-read gates that need a counter surviving deploys. Each row
represents one named gate; ``consecutive_agreements`` increments per matching
parallel-read result and resets on divergence. When it reaches the gate's
agreement threshold the read path flips by setting ``flipped = true``.

For the agent_invocation_log dual-write window the relevant row is
``agent_invocation_log_quota_parity``. See
``app/services/agent_invocation_logger.py`` for the gate primitives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MigrationGate(Base):
    __tablename__ = "migration_gates"

    name: Mapped[str] = mapped_column(sa.String(80), primary_key=True)
    consecutive_agreements: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    total_checks: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    total_divergences: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    flipped: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    last_divergence_payload: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=sa.func.now(),
        nullable=False,
    )


GATE_QUOTA_PARITY = "agent_invocation_log_quota_parity"
