from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool: ConnectionPool | None = None


def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


async def get_redis() -> Redis:  # type: ignore[type-arg]
    return Redis(connection_pool=get_redis_pool())


def redis_key(raw: str) -> str:
    """Namespace a Redis key with the configured prefix.

    Usage:
        await redis.get(redis_key("conv:abc123"))
        # → "pae:conv:abc123"

    This prevents key collisions when multiple environments (dev, staging, prod)
    share the same Redis instance.
    """
    return f"{settings.redis_key_prefix}:{raw}"
