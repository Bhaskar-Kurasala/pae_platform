"""Request-scoped correlation IDs.

D19.1 CP1.1 extension — emits two correlation IDs at request entry:

  - ``request_id`` (UUID4 string, 36 chars; existing) — exposed on the
    ``X-Request-ID`` request/response header for client-side debugging
    and operator grep.
  - ``trace_id`` (W3C-trace-context-compatible 32-hex; new) — derived
    from the same UUID4 bytes so the two IDs share a single underlying
    identity. CP3 will wire this into outbound W3C ``traceparent``
    propagation; CP1 just binds it into the structlog context so every
    log line emitted during the request carries it.

Defensive read of W3C ``traceparent`` (CP1.1.c): if a caller supplies
a well-formed ``traceparent`` header we adopt the trace-id portion so
upstream proxies / future internal callers that already speak W3C are
honoured. Malformed values are ignored — we never raise from here. Full
W3C wire-format support (parent-id, sampled flag, outbound propagation)
is CP3 scope.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"
TRACEPARENT_HEADER = "traceparent"

# W3C traceparent format: "<version>-<trace-id>-<parent-id>-<flags>"
# version: 2 hex; trace-id: 32 hex; parent-id: 16 hex; flags: 2 hex.
# Total 55 chars when version="00". We only consume trace-id at CP1.
_TRACEPARENT_RE = re.compile(
    r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$"
)

log = structlog.get_logger()


def _trace_id_from_uuid(value: uuid.UUID) -> str:
    """Render a UUID's 16 raw bytes as the 32-hex W3C trace-id form."""
    return value.hex


def _parse_traceparent(value: str | None) -> str | None:
    """Return the 32-hex trace-id from a W3C traceparent header, or None.

    Bare-minimum parse — if the value is malformed in any way we return
    None and let the middleware generate a fresh trace_id. Defensive by
    design; CP3 owns full propagation semantics.
    """
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value.strip().lower())
    if not match:
        return None
    trace_id = match.group(1)
    # All-zeros trace-id is invalid per the W3C spec.
    if trace_id == "0" * 32:
        return None
    return trace_id


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Propagate / generate request-scoped correlation IDs.

    Behaviour:

      - Read ``X-Request-ID`` from the incoming request (existing
        contract). When present we trust it — upstream proxies (nginx,
        Fly's edge) own the namespace.
      - When absent, generate a new UUID4. This is the
        single-source-of-truth identity; ``trace_id`` is derived from
        its bytes so logs grepped by either ID land on the same
        request.
      - Read W3C ``traceparent`` defensively — if present and well-
        formed we adopt the trace-id portion. (Otherwise derive from
        request_id.)
      - Bind both ``request_id`` and ``trace_id`` to structlog
        contextvars for the request lifetime so every log line emitted
        during the request — including from non-middleware code paths
        like the DB layer or tool calls — carries the correlation IDs
        without any plumbing at the call site.
      - Echo ``X-Request-ID`` back in the response so clients can
        report the ID alongside an error.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming_request_id = request.headers.get(REQUEST_ID_HEADER)
        if incoming_request_id:
            request_id = incoming_request_id
            # We can't derive a trace_id from an arbitrary upstream
            # request_id (it isn't a UUID by contract), so we generate
            # a fresh one — falls back to traceparent below if present.
            trace_id_seed = uuid.uuid4()
        else:
            generated = uuid.uuid4()
            request_id = str(generated)
            trace_id_seed = generated

        # CP1.1.c — defensive W3C traceparent read.
        traceparent_trace_id = _parse_traceparent(
            request.headers.get(TRACEPARENT_HEADER)
        )
        trace_id = traceparent_trace_id or _trace_id_from_uuid(trace_id_seed)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            trace_id=trace_id,
        )
        try:
            response: Response = await call_next(request)
        finally:
            # Defensive unbind so a worker process that re-uses the
            # asyncio task between requests can never leak context.
            # bind_contextvars uses ContextVar under the hood so this
            # is mostly belt-and-braces, but cheap.
            structlog.contextvars.unbind_contextvars(
                "request_id", "trace_id"
            )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
