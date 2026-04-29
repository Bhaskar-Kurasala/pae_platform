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
"""

from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import REQUEST_ID_HEADER

log = structlog.get_logger()


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
    """
    request_id = request.headers.get(REQUEST_ID_HEADER) or "unknown"

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
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "type": "http_error",
                    "message": str(exc.detail),
                    "request_id": request_id,
                }
            },
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
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "type": "internal_error",
                "message": (
                    "Something went wrong on our side. We've logged it. "
                    "Reference this ID with support: " + request_id
                ),
                "request_id": request_id,
            }
        },
        headers={REQUEST_ID_HEADER: request_id},
    )
