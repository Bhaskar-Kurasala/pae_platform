"""ORM model for `agent_tool_calls` (Agentic OS — Primitive 2).

Audit row for every tool execution. The ToolExecutor writes one of
these around every dispatch, regardless of whether the call succeeded.
This is the single source of truth for "what did the agent actually
do?" — admins use it for forensics, evaluators use it for prompt
quality scoring, and ops uses it to spot misbehaving tools (timeouts,
repeated errors).
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


class AgentToolCall(Base, UUIDMixin):
    __tablename__ = "agent_tool_calls"

    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Loose join to AgentCallChain.root_id; not a FK because tool calls
    # often pre-date their containing chain row insert ordering.
    call_chain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ok','error','timeout')",
            name="agent_tool_calls_status_chk",
        ),
    )
