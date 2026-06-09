"""ORM model for `agent_memory` (Agentic OS — Primitive 1).

Persistent long-term memory for any agent. Hybrid recall: structured
(key match) + semantic (cosine similarity over `embedding`). The
column dimension is set in 0054_agentic_os_primitives.py and
mirrored here as `EMBEDDING_DIM` so the application layer doesn't
have to read the migration file to know the size.

`scope` controls the memory's reach:
  • user   — bound to one student (RLS-friendly default)
  • agent  — shared across one agent's calls but not student-bound
  • global — every agent can recall it; use sparingly
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin

# Mirror of the migration's EMBEDDING_DIM. If you change one, change
# both — there is no runtime check that flags a mismatch beyond a
# database error on insert.
EMBEDDING_DIM = 1536

# postgresql.ENUM (not sa.Enum) so `create_type=False` is honoured —
# the migration owns the CREATE TYPE; ORM metadata only references it.
MemoryScope = ENUM(
    "user", "agent", "global", name="agent_memory_scope", create_type=False
)


class AgentMemory(Base, UUIDMixin):
    __tablename__ = "agent_memory"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(MemoryScope, nullable=False, server_default="user")
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    valence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.0"
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="1.0"
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    access_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "valence BETWEEN -1.0 AND 1.0", name="agent_memory_valence_range"
        ),
        CheckConstraint(
            "confidence BETWEEN 0.0 AND 1.0",
            name="agent_memory_confidence_range",
        ),
    )
