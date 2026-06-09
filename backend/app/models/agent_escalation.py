"""ORM model for `agent_escalations` (Agentic OS — Primitive 4).

Terminal record when an agent's retry budget runs out. We still
return the best attempt to the caller (escalated=True flag in
AgentResult), but the row here ensures the admin notification
pipeline has something to read.

`reason` is human-readable copy from the critic's last reasoning
plus a short prefix ("eval below 0.6 after 2 attempts"). Frontend
admin views render this verbatim — keep it readable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class AgentEscalation(Base, UUIDMixin):
    __tablename__ = "agent_escalations"

    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    call_chain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    best_attempt: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    notified_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
