"""Saved skill path — one row per student, upserted on each save (#24)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class SavedSkillPath(Base, UUIDMixin, TimestampMixin):
    """Persists a student's manually saved learning path as a JSON list of UUIDs.

    Uses Text (not JSONB) so the model works with SQLite in tests.
    """

    __tablename__ = "saved_skill_paths"
    __table_args__ = (UniqueConstraint("user_id", name="uq_saved_skill_paths_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # JSON-encoded list[str] of skill UUID strings
    skill_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
