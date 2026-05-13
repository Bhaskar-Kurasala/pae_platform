import enum
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TokenType(str, enum.Enum):
    password_reset = "password_reset"
    email_verify = "email_verify"
    email_change = "email_change"


# Expiry per token type — single source of truth consumed by the repository.
TOKEN_TTL: dict[TokenType, timedelta] = {
    TokenType.password_reset: timedelta(hours=1),
    TokenType.email_verify: timedelta(hours=24),
    TokenType.email_change: timedelta(hours=1),
}


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # sha256 hex digest of the raw token — never store raw token.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_type: Mapped[TokenType] = mapped_column(
        Enum(TokenType, name="auth_token_type", create_type=False),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL until consumed (single-use enforcement).
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Audit trail — the IP address that requested the token.
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    user: Mapped["User"] = relationship("User", lazy="select")

    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    def is_used(self) -> bool:
        return self.used_at is not None

    def is_valid(self) -> bool:
        return not self.is_expired() and not self.is_used()


from app.models.user import User  # noqa: E402
