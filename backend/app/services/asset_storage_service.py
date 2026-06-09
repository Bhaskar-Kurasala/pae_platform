"""AssetStorageService — Cloudflare R2 presigned GET URLs for notebook assets.

R2 is S3-compatible. boto3 mints the presigned GET locally (pure CPU,
no network round trip), so the route can call this synchronously without
touching the event loop in any meaningful way.

Why R2:
  * Egress is free, which matters once we have hundreds of students
    fetching multi-MB .ipynb files repeatedly.
  * S3-compatible API means boto3 works as-is.

Dev fallback: when R2 isn't configured we return a deterministic path
under the local content dir so dev work doesn't need a Cloudflare account.
The frontend's JupyterLite host serves these directly in dev.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING
from urllib.parse import quote

import structlog

from app.core.config import settings

if TYPE_CHECKING:
    from botocore.client import BaseClient


log = structlog.get_logger()


@dataclass(frozen=True)
class SignedAssetUrl:
    url: str
    expires_at: datetime
    signed: bool


@lru_cache(maxsize=1)
def _client() -> "BaseClient | None":
    """Build (and cache) the R2 boto3 client. None when not configured."""
    if not (
        settings.r2_account_id
        and settings.r2_access_key
        and settings.r2_secret_key
        and settings.r2_endpoint
    ):
        return None
    # Lazy import — boto3 is heavy; avoid pulling it in for tests that
    # never touch the storage layer.
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key,
        aws_secret_access_key=settings.r2_secret_key,
        region_name=settings.r2_region,
        config=BotoConfig(signature_version="s3v4"),
    )


def signed_notebook_url(
    object_key: str,
    *,
    ttl_seconds: int | None = None,
) -> SignedAssetUrl:
    """Mint a presigned GET URL for an R2 object key.

    Returns a degraded "unsigned" URL pointing at the local content
    proxy when R2 isn't configured (dev mode). The route never branches
    on this — it just hands the URL back to the client.
    """
    ttl = ttl_seconds or settings.r2_signed_url_ttl_seconds
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    client = _client()

    if client is None:
        log.warning(
            "r2.signed_url.unsigned",
            reason="R2 credentials not set; using dev passthrough",
            object_key=object_key,
        )
        # Local dev: serve directly out of the content dir via the
        # frontend's static handler (or a backend proxy you wire up).
        # Keeping the fallback simple — production validator will
        # refuse to boot without R2 credentials so this branch never
        # runs in prod.
        return SignedAssetUrl(
            url=f"/api/v1/learn/local-asset/{quote(object_key, safe='/')}",
            expires_at=expires_at,
            signed=False,
        )

    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket, "Key": object_key},
        ExpiresIn=ttl,
    )
    return SignedAssetUrl(url=url, expires_at=expires_at, signed=True)


def jupyterlite_launch_url(signed_url: str) -> str:
    """Build the JupyterLite launch URL that opens the notebook on load.

    JupyterLite reads `?fromURL=<encoded>` and fetches the notebook
    into the in-browser kernel. We pass the SHORT-LIVED signed URL so
    the kernel can fetch the .ipynb during the token's TTL window.
    """
    base = settings.jupyterlite_base_url.rstrip("/")
    return f"{base}/lab/index.html?fromURL={quote(signed_url, safe='')}"
