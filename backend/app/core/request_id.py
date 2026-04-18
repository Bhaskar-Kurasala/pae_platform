import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Propagate or generate a request-scoped correlation ID.

    - Reads ``X-Request-ID`` from incoming headers (trusted from upstream proxies).
    - If absent, generates a new UUID4.
    - Binds the ID into structlog context vars so every log line in the request
      automatically includes ``request_id``.
    - Echoes the ID back in the response header so clients can correlate errors.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
