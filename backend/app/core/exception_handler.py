"""PR2/B4.1 — global exception handler middleware.

Goal: every uncaught exception in a route becomes:
  1. A structured log line with full context (`event`, `request_id`,
     `user_id`, `route`, exception type + message + traceback).
  2. A stable JSON response of the form
       {"error": {"type": "internal_error", "message": "...",
                  "request_id": "..."}}
  3. NEVER leaks a Python traceback to the client.

The handler is registered in `main.py` against the bare `Exception` class
so it catches anything FastAPI/Starlette doesn't already handle (e.g.
`HTTPException` is handled upstream by FastAPI's own machinery — those
keep their nice JSON detail intact).

We deliberately do NOT swallow `RateLimitExceeded` here — slowapi has its
own handler registered before us.

Also handles the upstream-LLM-rate-limit case below. Anthropic /
MiniMax 429s used to bubble out as opaque 500 errors with the generic
"something went wrong" message; the dedicated llm_rate_limit_handler
turns them into a structured 503 so frontend code can render typed
"Reviewer at capacity" copy instead of a panic toast.
"""

from __future__ import annotations

import anthropic
import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import REQUEST_ID_HEADER

log = structlog.get_logger()


def _current_trace_id(request: Request) -> str | None:
    """D19.2 / CP1.5 — pull the W3C trace_id for the response envelope.

    Reads from ``request.state.trace_id`` first (set by
    RequestIDMiddleware at request entry; survives even when this
    handler runs after the middleware's contextvar cleanup).
    Falls back to ``structlog.contextvars`` when state is unset
    (e.g., handler invoked from a non-request path during tests).
    """
    state_trace = getattr(request.state, "trace_id", None)
    if isinstance(state_trace, str) and state_trace:
        return state_trace
    ctx = structlog.contextvars.get_contextvars() or {}
    trace_id = ctx.get("trace_id")
    if isinstance(trace_id, str) and trace_id:
        return trace_id
    return None


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for anything that escaped a route.

    Behavior is deterministic regardless of the exception type:
      - `HTTPException` shouldn't reach us (FastAPI handles those before
        the global handler), but if a user code path raised a Starlette
        `HTTPException` we let its status_code through with the same
        stable shape so the client doesn't have to special-case.
      - Everything else → 500 with `internal_error`.

    D19.2 / CP1.5 — response shape extended with ``trace_id`` (when
    bound by D19.1 CP1's RequestIDMiddleware) so the frontend
    GracefulFailureMessage component can surface the canonical W3C
    32-hex form for support correlation. ``request_id`` is
    preserved for backwards compatibility with existing frontend
    error UX.
    """
    # Prefer request.state.request_id (set by RequestIDMiddleware at
    # entry — D19.2 CP1.5) so we surface the generated UUID when no
    # client header was present. Fall back to the incoming header
    # for legacy callers, finally to "unknown".
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get(REQUEST_ID_HEADER)
        or "unknown"
    )
    trace_id = _current_trace_id(request)

    if isinstance(exc, StarletteHTTPException):
        # Let HTTPException pass through with its declared status, but
        # in our shape so frontend error handling is one branch.
        log.warning(
            "http.exception_unhandled_path",
            status_code=exc.status_code,
            detail=str(exc.detail),
            path=request.url.path,
            method=request.method,
            request_id=request_id,
        )
        error_payload: dict[str, str | None] = {
            "type": "http_error",
            "message": str(exc.detail),
            "request_id": request_id,
        }
        if trace_id is not None:
            error_payload["trace_id"] = trace_id
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": error_payload},
            headers={REQUEST_ID_HEADER: request_id},
        )

    # The real catch — internal errors that escaped the route.
    log.error(
        "unhandled_exception",
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        path=request.url.path,
        method=request.method,
        request_id=request_id,
        exc_info=exc,
    )
    error_payload = {
        "type": "internal_error",
        # D19.2 D-C — graceful-failure UX wording. Honest about the
        # unknown without leaking internals or creating user anxiety.
        "user_message": (
            "Something went wrong, please try again. We've logged "
            "this and we're looking into it."
        ),
        # Backwards-compat: prior shape used "message" with the
        # request_id concatenated. Frontend consumers reading the
        # "message" field still work; new consumers should read
        # "user_message" + "trace_id" / "request_id" separately.
        "message": (
            "Something went wrong on our side. We've logged it. "
            "Reference this ID with support: " + request_id
        ),
        "request_id": request_id,
    }
    if trace_id is not None:
        error_payload["trace_id"] = trace_id
    return JSONResponse(
        status_code=500,
        content={"error": error_payload},
        headers={REQUEST_ID_HEADER: request_id},
    )


async def llm_rate_limit_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Dedicated handler for upstream LLM rate-limit / timeout errors.

    Registered against ``anthropic.RateLimitError`` and
    ``anthropic.APITimeoutError`` in main.py. Any route that calls
    Claude / MiniMax without its own try/except still surfaces a
    truthful 503 instead of a generic 500.

    Response shape mirrors the global handler so the frontend can
    consume one envelope. ``type: "rate_limited"`` lets typed error
    UI (see classifyReviewError on the frontend) render the right
    "Reviewer at capacity — try again in 30-60s" copy instead of
    the catch-all "something went wrong" toast.
    """
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get(REQUEST_ID_HEADER)
        or "unknown"
    )
    trace_id = _current_trace_id(request)

    is_timeout = isinstance(exc, anthropic.APITimeoutError)
    log.warning(
        "llm.rate_limited" if not is_timeout else "llm.timeout",
        exception_type=type(exc).__name__,
        path=request.url.path,
        method=request.method,
        request_id=request_id,
    )

    error_payload: dict[str, str | None] = {
        "type": "rate_limited",
        "user_message": (
            "Our reviewer is at capacity right now. Try again in 30-60s — "
            "your work is saved."
        ),
        "message": "Reviewer is at capacity — try again in 30-60s.",
        "request_id": request_id,
    }
    if trace_id is not None:
        error_payload["trace_id"] = trace_id
    return JSONResponse(
        status_code=503,
        content={"error": error_payload},
        headers={REQUEST_ID_HEADER: request_id, "Retry-After": "30"},
    )
