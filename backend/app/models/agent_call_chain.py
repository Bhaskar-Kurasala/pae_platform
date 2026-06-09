"""ORM model for `agent_call_chain` (Agentic OS — Primitive 3).

One row per inter-agent invocation. `root_id` is shared across every
link in a single outermost execute(); `parent_id` walks the call
graph upward. Status values:

  ok                — call returned cleanly
  error             — callee raised; caller saw an exception
  cycle             — caller→callee pair already on the chain (cycle)
  depth_exceeded    — chain depth >= agent_call_max_depth at write
                      time (default 5)

We log the chain row even on rejection (cycle / depth_exceeded) so
the trace is complete — the caller learns by checking `status`, not
by an empty audit.
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


class AgentCallChain(Base, UUIDMixin):
    __tablename__ = "agent_call_chain"

    root_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    caller_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    callee_agent: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ok','error','cycle','depth_exceeded')",
            name="agent_call_chain_status_chk",
        ),
        CheckConstraint("depth >= 0", name="agent_call_chain_depth_nonneg"),
    )
