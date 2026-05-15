"""MuxService — sign Mux playback JWTs and verify Mux webhooks.

Mux uses signed playback URLs for protected video. The flow:

  1. Course author uploads video → Mux returns playback_id + asset_id.
  2. We persist playback_id as ``LessonAsset.storage_ref`` (kind='video').
  3. On request, the route calls ``mint_playback_token(playback_id)``;
     we return a JWT signed with our Mux signing key (RS256).
  4. Frontend MuxPlayer attaches ``token=<jwt>`` to the playback URL.

Webhooks: Mux posts watched-time events; we verify the HMAC signature
in ``verify_webhook_signature`` and dedup by event_id at the service layer.

Dev mode (no Mux signing key configured): ``mint_playback_token`` returns
an empty token + a degraded response. The frontend falls back to public
playback for local testing; production refuses to boot without the key
via the validator below.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from app.core.config import settings

log = structlog.get_logger()


@dataclass(frozen=True)
class PlaybackToken:
    token: str  # empty string in dev when no signing key is configured
    playback_id: str
    expires_at: datetime
    signed: bool


def _signing_key_pem() -> str | None:
    """Return the RSA private key PEM, expanding escaped newlines.

    Fly secrets and many CI env stores collapse newlines to ``\n`` literal
    sequences inside the env var. We restore them so the key parses as
    valid PEM. Returns None when the key isn't configured.
    """
    raw = settings.mux_signing_key_private
    if not raw:
        return None
    return raw.replace("\\n", "\n")


def _is_signing_configured() -> bool:
    return bool(settings.mux_signing_key_id) and _signing_key_pem() is not None


def mint_playback_token(
    playback_id: str,
    *,
    ttl_seconds: int | None = None,
) -> PlaybackToken:
    """Mint a short-lived signed playback JWT for a Mux playback_id.

    `aud` is fixed to "v" (video) per the Mux signed-URL spec.
    `kid` is the signing key id Mux issued; Mux uses it to look up the
    public half and verify the signature on every playback request.
    """
    ttl = ttl_seconds or settings.mux_playback_token_ttl_seconds
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

    if not _is_signing_configured():
        # Dev fallback. Frontend handles the empty token gracefully by
        # attempting public playback; useful when running against a Mux
        # public asset locally. Production refuses to boot without keys.
        log.warning(
            "mux.playback_token.unsigned",
            reason="MUX_SIGNING_KEY_ID / MUX_SIGNING_KEY_PRIVATE not set",
            playback_id=playback_id,
        )
        return PlaybackToken(
            token="",
            playback_id=playback_id,
            expires_at=expires_at,
            signed=False,
        )

    # Lazy import — python-jose is the JWT lib already vendored.
    from jose import jwt as jose_jwt

    payload = {
        "sub": playback_id,
        "aud": "v",
        "exp": int(expires_at.timestamp()),
        "kid": settings.mux_signing_key_id,
    }
    token = jose_jwt.encode(
        payload,
        _signing_key_pem(),
        algorithm="RS256",
        headers={"kid": settings.mux_signing_key_id},
    )
    return PlaybackToken(
        token=token,
        playback_id=playback_id,
        expires_at=expires_at,
        signed=True,
    )


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def verify_webhook_signature(*, signature_header: str, body: bytes) -> bool:
    """Verify a `Mux-Signature` header against the configured webhook secret.

    Mux signs as ``t=<unix_ts>,v1=<hex_hmac>`` (same shape as Stripe).
    We compute HMAC-SHA256 over ``f"{ts}.{body_str}"`` with the secret,
    compare in constant time, and reject signatures older than 5 min.

    Returns False (not raises) so the route can decide the response code.
    """
    secret = settings.mux_webhook_secret
    if not secret:
        log.warning("mux.webhook.secret_not_configured")
        return False
    if not signature_header:
        return False

    parts = dict(
        kv.strip().split("=", 1)
        for kv in signature_header.split(",")
        if "=" in kv
    )
    ts = parts.get("t")
    sig = parts.get("v1")
    if not ts or not sig:
        return False

    try:
        ts_int = int(ts)
    except ValueError:
        return False
    if abs(time.time() - ts_int) > 300:
        log.warning("mux.webhook.signature_too_old", ts=ts)
        return False

    signed_payload = f"{ts}.{body.decode('utf-8', errors='replace')}".encode()
    expected = hmac.new(
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


# ---------------------------------------------------------------------------
# Convenience: derive a stable thumbnail URL.
# ---------------------------------------------------------------------------


def thumbnail_url(playback_id: str, *, time_seconds: int = 5) -> str:
    """Public thumbnail URL for a playback_id; used by the lesson card."""
    return (
        f"https://image.mux.com/{playback_id}/thumbnail.jpg"
        f"?time={time_seconds}"
    )


def signing_health() -> dict[str, object]:
    """Operator helper — surfaces config state without leaking the key."""
    pem = _signing_key_pem()
    return {
        "signing_configured": _is_signing_configured(),
        "key_id_present": bool(settings.mux_signing_key_id),
        "private_key_present": bool(pem),
        "private_key_looks_pem": bool(
            pem and pem.startswith("-----BEGIN")
        ),
        "webhook_secret_present": bool(settings.mux_webhook_secret),
    }


# ---------------------------------------------------------------------------
# Production-required validator helper. Imported by main.py at startup
# to surface a misconfigured Mux env BEFORE the first lesson request.
# ---------------------------------------------------------------------------


def assert_production_ready() -> None:
    """Raise RuntimeError if production is missing Mux signing material."""
    health = signing_health()
    missing = [k for k, v in health.items() if not v]
    if missing and settings.environment.lower() == "production":
        raise RuntimeError(
            "Mux signing not fully configured for production: missing "
            + ", ".join(missing)
        )
