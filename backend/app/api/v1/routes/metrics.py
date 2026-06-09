"""D19.1 CP2 — Prometheus /metrics scrape endpoint.

Mounted at the application root (``/metrics``) so Fly.io's built-in
Prometheus scraping and any external scraper can hit it at the
conventional path. Wrapped in HTTP Basic auth driven by env vars
(METRICS_USERNAME / METRICS_PASSWORD) because an unauthenticated
metrics endpoint is a non-trivial information disclosure surface.

Auth contract:

  - When METRICS_USERNAME and METRICS_PASSWORD are both set: the
    endpoint requires Basic auth matching exactly. Wrong creds →
    401. No header → 401 with ``WWW-Authenticate: Basic`` so a
    scraper sees the challenge.

  - When *either* env var is unset: the endpoint refuses every
    request with 503. This is the safe default — production
    deployment must set both, OR explicitly disable the route by
    not including this router. We intentionally do NOT default to
    open-access; an unauthenticated scrape endpoint left in by
    accident is the textbook misconfiguration.

  - Constant-time comparison (``secrets.compare_digest``) so a
    timing attacker can't enumerate either field byte-by-byte.

Response shape: standard Prometheus text exposition format from
``app.core.metrics.render_latest`` against the canonical REGISTRY.
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response

from app.core.metrics import render_latest

router = APIRouter(tags=["metrics"])


_REALM = "aicareeros-metrics"
_UNAUTH_HEADERS = {"WWW-Authenticate": f'Basic realm="{_REALM}"'}


def _check_basic_auth(request: Request) -> None:
    """Raise 401/503 unless the request carries valid Basic creds.

    Reads METRICS_USERNAME / METRICS_PASSWORD at call time (not
    import time) so an env update without a restart still moves to
    the new credentials at the next scrape; we only ever pay the
    cost of two ``os.environ.get`` lookups per scrape.
    """
    expected_user = os.environ.get("METRICS_USERNAME")
    expected_pass = os.environ.get("METRICS_PASSWORD")

    # No creds configured → fail closed.
    if not expected_user or not expected_pass:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "metrics endpoint unconfigured: set METRICS_USERNAME "
                "and METRICS_PASSWORD env vars to enable scraping"
            ),
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Basic authentication required",
            headers=_UNAUTH_HEADERS,
        )

    try:
        decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Basic credentials",
            headers=_UNAUTH_HEADERS,
        ) from None

    if ":" not in decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Basic credentials",
            headers=_UNAUTH_HEADERS,
        )

    user, _, password = decoded.partition(":")

    # compare_digest on both fields independently, then AND. This
    # avoids an early-return on user mismatch that would let a
    # timing attacker decide username before attacking password.
    user_ok = secrets.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8"))
    pass_ok = secrets.compare_digest(password.encode("utf-8"), expected_pass.encode("utf-8"))
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid metrics credentials",
            headers=_UNAUTH_HEADERS,
        )


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus text exposition of REGISTRY. Requires Basic auth."""
    _check_basic_auth(request)
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
