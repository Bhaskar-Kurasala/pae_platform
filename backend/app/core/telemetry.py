"""PR3/C3.1 — backend telemetry (PostHog).

Single chokepoint for all server-side product analytics.

Design rules:

  1. **No-op safe.** When `POSTHOG_KEY` is unset or `posthog-node` is
     not installed, every public function silently does nothing. Dev,
     CI, and self-hosted deployments without telemetry must work
     identically to a production deploy with PostHog wired up — they
     just stop emitting events. We never raise from here.

  2. **One init.** A module-level `_client` initialized on first use,
     guarded by an `_initialized` flag. Workers that fork (Celery)
     re-init on first event in the worker process; the SDK handles
     this safely.

  3. **Thin wrapper.** We intentionally do not add a typed event
     catalog at this layer — that lives in the call sites in PR3/C3.2.
     This module just gives us `capture(distinct_id, event, properties)`
     and `flush()`.

  4. **Async-friendly.** PostHog's Python SDK is sync; calls are fire-
     and-forget (it has its own background queue). We expose `capture`
     as a normal `def` and let callers invoke it from inside async
     handlers without `await`.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger()

# Module-level singleton. None means either not configured yet, or
# permanently disabled (no key set).
_client: Any | None = None
_initialized: bool = False


def _maybe_init() -> Any | None:
    """Lazy init. Returns the live client or None if telemetry is off."""
    global _client, _initialized

    if _initialized:
        return _client

    _initialized = True
    api_key = os.environ.get("POSTHOG_KEY")
    if not api_key:
        log.info("telemetry.posthog_disabled", reason="POSTHOG_KEY not set")
        return None

    try:
        # Imported lazily so an optional dep doesn't crash the boot.
        from posthog import Posthog  # type: ignore[import-not-found]
    except ImportError:
        log.warning(
            "telemetry.posthog_disabled",
            reason="posthog package not installed",
        )
        return None

    host = os.environ.get("POSTHOG_HOST", "https://app.posthog.com")
    try:
        _client = Posthog(api_key, host=host)
        log.info("telemetry.posthog_enabled", host=host)
    except Exception as exc:
        log.warning("telemetry.posthog_init_failed", error=str(exc))
        _client = None

    return _client


def capture(
    distinct_id: str | None,
    event: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Fire a PostHog event. No-op if telemetry is disabled.

    Args:
        distinct_id: The user's UUID (str) or None for anonymous events.
                     Anonymous events get bucketed by a literal "anon"
                     id so server-side aggregations still see them.
        event:       Snake_case event name (e.g. "today.warmup_done").
        properties:  Arbitrary structured props attached to the event.

    We swallow every exception from the SDK so a PostHog outage can
    never take down a request handler.
    """
    client = _maybe_init()
    if client is None:
        return

    try:
        client.capture(
            distinct_id=distinct_id or "anon",
            event=event,
            properties=properties or {},
        )
    except Exception as exc:
        # Soft fail — telemetry is never load-bearing.
        # NB: structlog reserves the positional first arg as `event`,
        # so we rename our kwarg to `event_name` to avoid the
        # `multiple values for argument 'event'` collision.
        log.warning(
            "telemetry.capture_failed",
            event_name=event,
            error=str(exc),
        )


def flush() -> None:
    """Force the SDK's background queue to drain. Useful at app
    shutdown so events from the last request actually leave the
    process. No-op if telemetry is disabled."""
    client = _maybe_init()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        log.warning("telemetry.flush_failed", error=str(exc))
