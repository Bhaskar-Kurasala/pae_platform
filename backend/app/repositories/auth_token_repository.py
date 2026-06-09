import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_token import TOKEN_TTL, AuthToken, TokenType

log = structlog.get_logger()

# Tokens older than this beyond their expiry are permanently purged by the
# cleanup job. Kept short (7 days post-expiry) — audit trail need is low
# for consumed/expired tokens.
_CLEANUP_GRACE_DAYS = 7


def _hash_token(raw: str) -> str:
    """Return the sha256 hex digest of a raw token string."""
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthTokenRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_token(
        self,
        user_id: uuid.UUID,
        token_type: TokenType,
        ip_address: str | None = None,
    ) -> tuple[str, AuthToken]:
        """Generate a new token, persist its hash, return (raw_token, record).

        The raw token is returned exactly once — the caller is responsible for
        embedding it in the email link. It is never stored again.
        """
        raw = secrets.token_urlsafe(32)
        ttl: timedelta = TOKEN_TTL[token_type]
        record = AuthToken(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=_hash_token(raw),
            token_type=token_type,
            expires_at=datetime.now(UTC) + ttl,
            ip_address=ip_address,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        log.info(
            "auth_token.created",
            user_id=str(user_id),
            token_type=token_type.value,
            expires_at=record.expires_at.isoformat(),
        )
        return raw, record

    async def get_by_hash(self, raw: str) -> AuthToken | None:
        """Look up a token record by the raw token value (hashes internally)."""
        digest = _hash_token(raw)
        result = await self.db.execute(
            select(AuthToken).where(AuthToken.token_hash == digest)
        )
        return result.scalar_one_or_none()

    async def mark_used(self, record: AuthToken) -> AuthToken:
        """Stamp used_at = now() on the record. Idempotent if already used."""
        if record.used_at is None:
            record.used_at = datetime.now(UTC)
            self.db.add(record)
            await self.db.flush()
            log.info(
                "auth_token.consumed",
                user_id=str(record.user_id),
                token_type=record.token_type.value,
            )
        return record

    async def cleanup_expired(self) -> int:
        """Delete tokens expired more than _CLEANUP_GRACE_DAYS ago.

        Returns the count of deleted rows. Logs count without PII.
        """
        cutoff = datetime.now(UTC) - timedelta(days=_CLEANUP_GRACE_DAYS)
        result = await self.db.execute(
            delete(AuthToken)
            .where(AuthToken.expires_at < cutoff)
            .returning(AuthToken.id)
        )
        deleted = len(result.fetchall())
        if deleted:
            log.info("auth_token.cleanup", deleted_count=deleted)
        return deleted
