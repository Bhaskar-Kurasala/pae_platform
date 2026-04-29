"""PR3/C5.1 — backend Sentry integration.

Single chokepoint for FastAPI error reporting. Mirrors the design rules
of `app/core/telemetry.py`:

  1. **No-op safe.** When `SENTRY_DSN` is unset or `sentry-sdk` isn't
     installed, `init_sentry()` is a no-op. Dev / CI / self-hosted
     deploys without Sentry must work identically.

  2. **PII filtering.** A `before_send` hook strips well-known PII
     fields from the event before it leaves the process. We never
     send: request bodies (could contain student-pasted code with
     secrets), email/full_name (in the user dict), Authorization
     headers, Cookie headers, X-Refresh-Token headers.

  3. **Standard tags on every event.** `route` (from the FastAPI
     scope), `user_id` (from `request.state.user` if logged in),
     `agent_name` (when an MOA route was taken — set by the agent
     orchestrator via `sentry_sdk.set_tag` at the chokepoint). On-call
     can filter the issues board by any of those.

  4. **Structlog bridge.** `log.error` / `log.warning` calls during a
     request automatically attach as breadcrumbs to the event so
     debugging an issue gets the full structured-log timeline up to
     the failure.

  5. **No-init = silent fail.** Calls to `set_user_context` and
     `set_agent_context` are safe even when Sentry is disabled — they
     just do nothing. This way the call sites in routes/orchestrator
     can call freely without `if settings.sentry_dsn:` guards.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger()

_initialized: bool = False
_enabled: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_sentry() -> None:
    """Initialize the Sentry SDK from env vars. Safe to call multiple
    times (idempotent — second call no-ops)."""
    global _initialized, _enabled

    if _initialized:
        return
    _initialized = True

    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.info("sentry.disabled", reason="SENTRY_DSN not set")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        log.warning(
            "sentry.disabled", reason="sentry-sdk package not installed"
        )
        return

    environment = os.environ.get("ENVIRONMENT", "development")
    release = os.environ.get("BUILD_SHA")  # set by Docker / Fly at build time

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            # Conservative trace sampling so the free tier doesn't fill up.
            traces_sample_rate=float(
                os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")
            ),
            # Profiling off by default — opt-in via env.
            profiles_sample_rate=float(
                os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.0")
            ),
            # We strip PII ourselves; tell the SDK not to also send IPs.
            send_default_pii=False,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
            ],
            before_send=_before_send,
        )
        _enabled = True
        log.info("sentry.enabled", environment=environment, release=release)
    except Exception as exc:
        log.warning("sentry.init_failed", error=str(exc))
        _enabled = False


def is_enabled() -> bool:
    """Cheap read for call sites that want to skip work when Sentry
    isn't configured (e.g. constructing a heavy breadcrumb payload)."""
    return _enabled


def set_user_context(user_id: str | None) -> None:
    """Tag the current scope with the authenticated user's id. No-op if
    Sentry isn't enabled or `user_id` is None.

    We deliberately do NOT pass email / full_name / IP — `user_id` is
    enough to correlate to the platform DB without leaking PII into
    Sentry's vault.
    """
    if not _enabled or not user_id:
        return
    try:
        import sentry_sdk

        sentry_sdk.set_user({"id": user_id})
    except Exception as exc:
        log.debug("sentry.set_user_failed", error=str(exc))


def set_agent_context(agent_name: str | None) -> None:
    """Tag the current scope with the agent name when the MOA routes a
    chat. Lets on-call filter the issues list by `agent:socratic_tutor`
    when a specific agent regresses."""
    if not _enabled or not agent_name:
        return
    try:
        import sentry_sdk

        sentry_sdk.set_tag("agent_name", agent_name)
    except Exception as exc:
        log.debug("sentry.set_tag_failed", error=str(exc))


def capture_exception(exc: BaseException) -> None:
    """Manually report an exception that's been swallowed (e.g. inside
    a fire-and-forget background task that won't trip the FastAPI
    integration). No-op if disabled."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception as inner:
        log.debug("sentry.capture_failed", error=str(inner))


# ---------------------------------------------------------------------------
# PII-stripping `before_send`
# ---------------------------------------------------------------------------


# Header names we never want to ship to Sentry. Lower-cased; matched
# case-insensitively because Starlette stores them lower-cased anyway.
_REDACT_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "x-refresh-token",
        "x-csrf-token",
        "set-cookie",
    }
)

# Top-level user fields that may leak PII. We KEEP `id` because that's
# the explicit purpose of `set_user_context` — the platform DB is the
# source of truth for matching id → person.
_REDACT_USER_KEYS = frozenset({"email", "username", "ip_address", "full_name"})


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Strip PII from the event before it leaves the process.

    We mutate-in-place because Sentry passes us a fresh dict each call.
    Returning `None` would drop the event entirely; we always return
    the (cleaned) event so the issue still surfaces.
    """
    request = event.get("request")
    if isinstance(request, dict):
        # 1. Redact known-sensitive headers.
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if key.lower() in _REDACT_HEADERS:
                    headers[key] = "[redacted]"
        elif isinstance(headers, list):
            # Older format: list of [name, value] pairs.
            for pair in headers:
                if isinstance(pair, list | tuple) and len(pair) == 2:
                    if str(pair[0]).lower() in _REDACT_HEADERS:
                        pair[1] = "[redacted]"

        # 2. Drop request bodies entirely. They can contain pasted code
        # with API keys, secrets, or other student artefacts.
        if "data" in request:
            request["data"] = "[redacted]"

        # 3. Strip query string values if they look like tokens. Cheap
        # heuristic: anything > 32 chars in a `?...=...` pair gets
        # redacted. Keeps short keys like `?course=python-foundations`
        # intact for debugging.
        qs = request.get("query_string")
        if isinstance(qs, str) and "=" in qs:
            request["query_string"] = _redact_long_qs_values(qs)

    # 4. Strip non-id fields off the user dict.
    user = event.get("user")
    if isinstance(user, dict):
        for key in list(user.keys()):
            if key.lower() in _REDACT_USER_KEYS:
                user[key] = "[redacted]"

    return event


def _redact_long_qs_values(qs: str) -> str:
    """Replace any `key=value` pair where the value is > 32 chars."""
    parts: list[str] = []
    for kv in qs.split("&"):
        if "=" not in kv:
            parts.append(kv)
            continue
        key, _, value = kv.partition("=")
        if len(value) > 32:
            parts.append(f"{key}=[redacted]")
        else:
            parts.append(kv)
    return "&".join(parts)
