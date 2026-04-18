"""User tutor/UI preferences (P2-02+).

One row per user. Grown additively over Phase 2 — keep columns atomic, not
packed into a JSON blob, so we can index and query them directly when admin
dashboards need them later.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin

# Tutor modes:
#   standard       — default, balanced scaffolding + direct answers as needed.
#   socratic_strict — never gives direct answers. Questions only. (P2-02)
TUTOR_MODES = ("standard", "socratic_strict")


class UserPreferences(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tutor_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="standard", server_default="standard"
    )
    ugly_draft_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
