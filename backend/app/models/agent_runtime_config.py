"""AgentRuntimeConfig — runtime knobs per agent (kill switch, rate limits, prompt version)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentRuntimeConfig(Base):
    __tablename__ = "agent_runtime_config"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
