import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "positive" | "neutral" | "negative"
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    viewport_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    viewport_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, server_default="other"
    )
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recent_route_history: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
