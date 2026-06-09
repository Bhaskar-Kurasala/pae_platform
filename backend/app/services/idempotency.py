"""PR2/B6.1 — Redis-backed idempotency for write endpoints.

Pattern: caller hashes the canonical request payload, calls
`fetch_or_lock(key, ttl)` to either claim the slot or recover the
prior result. The first writer for a key gets `(False, None)` and is
responsible for doing the work and calling `store_result()`. Subsequent
callers within the TTL get `(True, <prior_result_json>)` and must
short-circuit — returning the cached payload to the client without
re-doing the side effect.

Ships with `make_request_hash()` so callers don't have to reinvent the
canonicalization. The hash is sha256 over the JSON-serialized payload
with sorted keys, so semantically-identical requests produce the same
fingerprint regardless of dict iteration order.

Why Redis and not a uniqueness constraint:
  - Some write paths use a per-click frontend ID (e.g. Practice's
    `practice-${Date.now()}`) that defeats `(user_id, message_id)`
    uniqueness. The content hash is the real identity.
  - We want a TIME-BOUNDED lock — saving the same content again 10
    minutes later is a legitimate "I edited my note" action, not a
    duplicate. A DB constraint would block it forever.
  - Redis already powers our SRS auto-seed cache and other short-TTL
    state, and we have `get_redis()` wired up in core.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog

log = structlog.get_logger()

DEFAULT_TTL_SECONDS = 60


def make_request_hash(*, user_id: str, payload: dict[str, Any]) -> str:
    """Deterministic fingerprint for an idempotent write.

    Includes the user id so two students saving an identical note
    don't collide. Sorts keys so `{a:1,b:2}` and `{b:2,a:1}` hash the
    same.
    """
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(f"{user_id}|{canon}".encode("utf-8")).hexdigest()
    # 16 hex chars = 64 bits of entropy. Plenty for a 60-second window.
    return h[:16]


def _key(prefix: str, request_hash: str) -> str:
    return f"idempotency:{prefix}:{request_hash}"


async def fetch_or_lock(
    *,
    prefix: str,
    request_hash: str,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> tuple[bool, dict[str, Any] | None]:
    """Atomically check-and-set the idempotency slot.

    Returns ``(replayed, prior_result)`` where:
      - ``replayed=False, prior_result=None`` — the caller is the first
        writer; do the work and call `store_result()` when done.
      - ``replayed=True, prior_result={...}`` — a write completed (or
        is in flight) for this hash; return the prior result without
        repeating the side effect.

    On Redis failure, fails-open: returns `(False, None)` so the write
    proceeds. Better to risk a duplicate than to block on a transient
    Redis blip.
    """
    try:
        # Imported lazily so the module is testable without redis libs
        # available; pytest paths that monkey-patch this won't trigger
        # the import at all.
        from app.core.redis import get_redis

        client = await get_redis()
        key = _key(prefix, request_hash)

        # SET key value NX EX ttl — atomic. Returns "OK" on first write,
        # None if the key already exists.
        acquired = await client.set(key, "in_flight", ex=ttl, nx=True)
        if acquired:
            return False, None

        # Slot was claimed. Read whatever is there.
        existing = await client.get(key)
        if existing is None:
            return False, None
        decoded = existing.decode("utf-8") if isinstance(existing, bytes) else str(existing)
        if decoded == "in_flight":
            # Concurrent first writer is still working. Return None so
            # the caller knows to short-circuit but has no prior result.
            return True, None
        try:
            return True, json.loads(decoded)
        except json.JSONDecodeError:
            # Corrupt slot — treat as fresh.
            return False, None
    except Exception as exc:
        log.warning("idempotency.redis_unavailable", prefix=prefix, error=str(exc))
        return False, None


async def store_result(
    *,
    prefix: str,
    request_hash: str,
    result: dict[str, Any],
    ttl: int = DEFAULT_TTL_SECONDS,
) -> None:
    """Persist the result of a successful write so a duplicate caller
    within the TTL gets the same response. Best-effort; logs on failure
    but never raises."""
    try:
        from app.core.redis import get_redis

        client = await get_redis()
        key = _key(prefix, request_hash)
        await client.set(key, json.dumps(result), ex=ttl)
    except Exception as exc:
        log.warning(
            "idempotency.store_failed", prefix=prefix, error=str(exc)
        )
