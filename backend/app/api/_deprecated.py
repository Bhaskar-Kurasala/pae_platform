"""
PR2/A4.1 — `@deprecated` route decorator + middleware.

Marks a FastAPI route handler as deprecated so that:

  1. Every response carries a stable `Deprecation: true` header (RFC 8594)
     and an optional `Sunset: <date>` header so clients (and the v8
     frontend audit job from PR1) can surface "this endpoint is
     scheduled to disappear" warnings.
  2. Each call emits a `log.warning("deprecated_endpoint_called", ...)`
     structlog event so we can grep production logs to find the last
     living caller before deletion. Drives PR2/A2.2 + A2.3 cleanup.

Headers are injected by `DeprecationHeaderMiddleware` (registered in
`app/main.py`) — it checks the matched route's endpoint for the
`__deprecated__` marker the decorator stamps on. This way we don't
have to retrofit a `response: Response` parameter onto 44 handler
signatures.

Usage:

    from app.api._deprecated import deprecated

    @router.get("/path/i/will/delete")
    @deprecated(sunset="2026-07-01", reason="superseded by /v2/path")
    async def get_thing(...) -> ...:
        ...
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

log = structlog.get_logger()

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def deprecated(
    *,
    sunset: str | None = None,
    reason: str | None = None,
) -> Callable[[F], F]:
    """
    Mark a route handler as deprecated.

    Args:
        sunset:  ISO-8601 date string (YYYY-MM-DD). Becomes the `Sunset`
                 header per RFC 8594.
        reason:  Human-readable reason ("superseded by /v2/path").
                 Logged and emitted as `Deprecation-Reason`.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = None
            r = kwargs.get("request")
            if isinstance(r, Request):
                request = r
            else:
                for a in args:
                    if isinstance(a, Request):
                        request = a
                        break

            user_id: str | None = None
            current_user = kwargs.get("current_user")
            if current_user is not None:
                user_id = str(getattr(current_user, "id", "")) or None

            log.warning(
                "deprecated_endpoint_called",
                route=request.url.path if request else func.__name__,
                method=request.method if request else None,
                user_id=user_id,
                sunset=sunset,
                reason=reason,
            )
            return await func(*args, **kwargs)

        wrapper.__deprecated__ = True  # type: ignore[attr-defined]
        wrapper.__deprecation_sunset__ = sunset  # type: ignore[attr-defined]
        wrapper.__deprecation_reason__ = reason  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


class DeprecationHeaderMiddleware(BaseHTTPMiddleware):
    """Adds Deprecation/Sunset/Deprecation-Reason headers to responses
    from any route whose endpoint was marked with `@deprecated`.

    Runs after the route is matched so we can read the endpoint's
    metadata; the marker is set as an attribute on the wrapped handler
    so it survives FastAPI's dependency-injection wrapping.
    """

    async def dispatch(  # type: ignore[override]
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)

        endpoint = request.scope.get("endpoint")
        if endpoint is None or not getattr(endpoint, "__deprecated__", False):
            return response

        response.headers["Deprecation"] = "true"
        sunset = getattr(endpoint, "__deprecation_sunset__", None)
        reason = getattr(endpoint, "__deprecation_reason__", None)
        if sunset:
            response.headers["Sunset"] = sunset
        if reason:
            response.headers["Deprecation-Reason"] = reason
        return response
