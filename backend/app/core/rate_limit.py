"""Rate limiting via slowapi.

Auth endpoints use stricter limits to prevent brute-force attacks.
All limits are per-IP using the X-Forwarded-For header (set by nginx).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Global limiter instance — mounted in main.py
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
