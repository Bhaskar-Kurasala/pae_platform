"""PortfolioAutopsyResult — persisted output of `/api/v1/receipts/autopsy`.

The autopsy endpoint scores a project across four axes (architecture,
failure-handling, observability, scope-discipline) and produces a retro.
Until now the result was returned and discarded; now it lands here so the
Proof Portfolio view can list past autopsies and the Application Kit can
include the strongest one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PortfolioAutopsyResult(Base):
    __tablename__ = "portfolio_autopsy_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_title: Mapped[str] = mapped_column(String(200), nullable=False)
    project_description: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # axes JSON shape:
    # { "architecture": {"score": int, "assessment": str},
    #   "failure_handling": {...}, "observability": {...},
    #   "scope_discipline": {...} }
    axes: Mapped[dict] = mapped_column(JSON, nullable=False)
    what_worked: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # what_to_do_differently JSON: list of {issue, why_it_matters,
    # what_to_do_differently}
    what_to_do_differently: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list
    )
    production_gaps: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    next_project_seed: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_request: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
