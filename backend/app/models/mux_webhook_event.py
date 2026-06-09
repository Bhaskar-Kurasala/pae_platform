"""MuxWebhookEvent — append-only Mux webhook ledger.

Mux delivers webhooks at-least-once. We dedup on `event_id` (the unique
id Mux assigns to every event) so replays are no-ops. `processed_at` is
NULL until our handler successfully wrote downstream state.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class MuxWebhookEvent(Base, UUIDMixin):
    __tablename__ = "mux_webhook_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_mux_webhook_events_event_id"),
    )

    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    playback_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    asset_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
