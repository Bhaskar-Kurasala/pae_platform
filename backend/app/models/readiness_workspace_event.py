"""ReadinessWorkspaceEvent — per-user click + view telemetry across the
Job Readiness workspace.

Captures view_opened / subnav_clicked / cta_clicked / kit_export_started /
jd_preset_selected / external_link_clicked etc. Schema is intentionally
generic (view + event + JSON payload) so we never need a migration to add
a new event type.

Best-effort writes: the frontend POSTs in batches every 5s or on view
change; failures are silent so analytics never blocks UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReadinessWorkspaceEvent(Base):
    __tablename__ = "readiness_workspace_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # overview | resume | jd | interview | proof | kit | global
    view: Mapped[str] = mapped_column(String(32), nullable=False)
    # view_opened, subnav_clicked, cta_clicked, kit_build_started, etc.
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Optional FK to a diagnostic session when the event happened in-flight.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "readiness_diagnostic_sessions.id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
