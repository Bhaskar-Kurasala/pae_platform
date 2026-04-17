"""Rate limiting via slowapi.

Auth endpoints use stricter limits to prevent brute-force attacks.
All limits are per-IP using the X-Forwarded-For header (set by nginx).
Uses Redis backend when available; falls back to in-memory for local dev/tests.
"""

import structlog
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

log = structlog.get_logger()


def _get_storage_uri() -> str:
    """Return Redis URI if reachable, else fall back to in-memory."""
    try:
        import redis as redis_lib  # type: ignore[import-untyped]

        r = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        r.close()
        return settings.redis_url
    except Exception:
        log.warning("rate_limit.redis_unavailable", fallback="memory://")
        return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    storage_uri=_get_storage_uri(),
)
