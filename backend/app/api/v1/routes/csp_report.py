"""CSP violation report endpoint.

Browsers send POST requests to this endpoint when a Content-Security-Policy
(or Content-Security-Policy-Report-Only) directive is violated.  The payload
is either application/csp-report (legacy) or application/json, both
containing a JSON object whose root key is "csp-report".

No authentication is required — browsers send these requests without any
credentials, and that is intentional.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Request, Response

log = structlog.get_logger()

router = APIRouter(prefix="/csp-report", tags=["security"])


@router.post(
    "/",
    status_code=204,
    summary="Receive CSP violation reports",
    description=(
        "Accepts browser-generated CSP violation reports "
        "(application/csp-report or application/json). "
        "No authentication required."
    ),
)
async def csp_report(request: Request) -> Response:
    body = await request.body()

    try:
        parsed: dict = json.loads(body)
    except json.JSONDecodeError:
        log.warning(
            "csp.violation.parse_error",
            raw=body.decode("utf-8", errors="replace")[:2000],
        )
        return Response(status_code=204)

    # application/csp-report wraps the data under the "csp-report" key.
    report = parsed.get("csp-report", parsed)
    log.warning("csp.violation", report=report)

    return Response(status_code=204)
