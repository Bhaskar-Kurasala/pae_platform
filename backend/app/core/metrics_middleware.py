"""D19.1 CP2 — FastAPI metrics middleware.

Increments ``aicareeros_api_requests`` and observes
``aicareeros_api_request_duration_seconds`` for every HTTP request.
Mounted alongside the existing CP1 RequestIDMiddleware in main.py.

Cardinality discipline (D-C):

  - The ``endpoint`` label is the matched FastAPI *route template*
    (``/api/v1/lessons/{id}``), NOT the request path. This keeps
    the label space bounded by the number of declared routes (low
    hundreds), regardless of traffic volume.

  - Requests that don't match a declared route (404s for
    typos / probes) are bucketed under ``endpoint='__not_found__'``
    so an attacker probing every UUID under the sun can't blow up
    the metric backend.

  - ``method`` is the HTTP verb (bounded enum: GET, POST, PUT,
    PATCH, DELETE, OPTIONS, HEAD).

  - ``status_code`` is the integer status as a string (bounded by
    HTTP spec).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp


class MetricsMiddleware(BaseHTTPMiddleware):
    """Emit api_requests + api_request_duration_seconds for every request."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    def _resolve_route_template(self, request: Request) -> str:
        """Walk the FastAPI router to find the route template that
        matched this request, so the metric label is the template
        (low cardinality) rather than the live path (high)."""
        router = request.app.router  # type: ignore[attr-defined]
        for route in getattr(router, "routes", []):
            try:
                match, _scope = route.matches(request.scope)
            except Exception:  # noqa: BLE001
                continue
            if match == Match.FULL:
                # Starlette routes expose `path` (the template).
                template = getattr(route, "path", None)
                if isinstance(template, str) and template:
                    return template
        return "__not_found__"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # The scrape endpoint itself is excluded from the metric so
        # Prometheus pulling /metrics every 15s doesn't dominate the
        # request-rate signal it produces.
        if request.url.path == "/metrics":
            return await call_next(request)

        # Local imports keep the cold-start cost off the import graph
        # of every module that pulls in main.py.
        from app.core.metrics import API_REQUEST_DURATION_SECONDS, API_REQUESTS

        start = time.monotonic()
        method = request.method
        endpoint = self._resolve_route_template(request)

        status_code: Any = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # Re-raise after recording the 5xx outcome — this matches
            # the FastAPI exception_handler stack: an unhandled
            # exception turns into a 500 by the time the client sees
            # it, and we want the metric to reflect that reality.
            status_code = 500
            raise
        finally:
            duration = time.monotonic() - start
            try:
                API_REQUESTS.labels(
                    endpoint=endpoint,
                    method=method,
                    status_code=str(status_code),
                ).inc()
                API_REQUEST_DURATION_SECONDS.labels(
                    endpoint=endpoint,
                    method=method,
                ).observe(duration)
            except Exception:  # noqa: BLE001
                # Metric emission must never break the request.
                pass
