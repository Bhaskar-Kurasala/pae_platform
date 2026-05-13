"""Batch 1 / D-A cleanup job: purge expired auth_tokens rows hourly."""
import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.repositories.auth_token_repository import AuthTokenRepository

log = structlog.get_logger()


@shared_task(name="app.tasks.cleanup_auth_tokens.cleanup_expired_auth_tokens")
def cleanup_expired_auth_tokens() -> dict[str, int]:
    """Delete auth_tokens rows expired more than 7 days ago.

    Runs in the Celery worker (sync entry point → async body via asyncio.run).
    Returns {"deleted": N} for the beat log.
    """
    import asyncio

    return asyncio.run(_async_cleanup())


async def _async_cleanup() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        repo = AuthTokenRepository(db)
        deleted = await repo.cleanup_expired()
        await db.commit()
        log.info("cleanup_auth_tokens.done", deleted_count=deleted)
        return {"deleted": deleted}
