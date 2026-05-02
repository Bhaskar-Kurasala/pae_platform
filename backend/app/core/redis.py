from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool: ConnectionPool | None = None

# P3 3B #163: every key written by the app goes through `namespaced_key`
# so a single Redis instance can safely host dev, staging, and prod
# without cross-talk. Categories are enumerated (not free-form strings)
# so `redis-cli --scan --pattern 'pae:prod:conv:*'` is a reliable tool.
_NAMESPACE_PREFIX = "pae"
_KEY_CATEGORIES = frozenset(
    {
        "conv",  # MOA conversation history (1h TTL)
        "courses",  # published course list cache
        "interview",  # mock-interview session store
        "quiz",  # pre-generated quiz versions keyed by message_id
        "notebook",  # P-Today2: bookmark summarization cache by message_id
        # Track 2 — Agentic OS escalation limiter. Per-agent
        # sorted set, scored by epoch seconds, ZREMRANGEBYSCORE
        # window of 3600s. See evaluation.RedisEscalationLimiter
        # for the full key shape.
        "escalation",
    }
)


def namespaced_key(category: str, *parts: str) -> str:
    """Return a fully-qualified Redis key.

    Format: ``pae:{environment}:{category}[:{part}[:{part}...]]``

    Raises ValueError for unknown categories — forcing new callers to
    register their key space here rather than scattering raw strings.
    """
    if category not in _KEY_CATEGORIES:
        raise ValueError(
            f"Unknown redis key category '{category}'. "
            f"Add it to _KEY_CATEGORIES in app/core/redis.py."
        )
    segments = [_NAMESPACE_PREFIX, settings.environment, category, *parts]
    return ":".join(segments)


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
