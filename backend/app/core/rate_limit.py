"""Rate limiting via slowapi.

Auth endpoints use stricter limits to prevent brute-force attacks.
All limits are per-IP using the X-Forwarded-For header (set by nginx).
Uses Redis backend so limits are enforced consistently across all workers.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Global limiter instance — mounted in main.py
# storage_uri points to Redis so counters are shared across gunicorn workers
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    storage_uri=settings.redis_url,
)
