"""StoryBank model — user STAR stories for behavioral interview preparation."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StoryBank(Base):
    __tablename__ = "story_bank"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    situation: Mapped[str] = mapped_column(sa.Text, nullable=False)
    task: Mapped[str] = mapped_column(sa.Text, nullable=False)
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    result: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # list of string tags e.g. ["leadership", "conflict", "scaling"]
    tags: Mapped[list | None] = mapped_column(sa.JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        onupdate=sa.func.now(),
        nullable=True,
    )
