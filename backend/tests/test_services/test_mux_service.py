"""Mux service: signature verification + dev-fallback playback token."""

from __future__ import annotations

import hashlib
import hmac
import time

from app.core.config import settings
from app.services import mux_service


def test_unsigned_token_when_keys_missing(monkeypatch):
    monkeypatch.setattr(settings, "mux_signing_key_id", "")
    monkeypatch.setattr(settings, "mux_signing_key_private", "")

    token = mux_service.mint_playback_token("playback_xyz")
    assert token.signed is False
    assert token.token == ""
    assert token.playback_id == "playback_xyz"


def test_webhook_signature_verifies_correct_signature(monkeypatch):
    secret = "whsec_test_super_secret"
    monkeypatch.setattr(settings, "mux_webhook_secret", secret)

    body = b'{"id":"evt_1","type":"video.asset.ready","data":{}}'
    ts = str(int(time.time()))
    expected = hmac.new(
        secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    header = f"t={ts},v1={expected}"

    assert (
        mux_service.verify_webhook_signature(signature_header=header, body=body)
        is True
    )


def test_webhook_signature_rejects_wrong_signature(monkeypatch):
    monkeypatch.setattr(settings, "mux_webhook_secret", "whsec_test_secret")
    ts = str(int(time.time()))
    bad_header = f"t={ts},v1=deadbeef"

    assert (
        mux_service.verify_webhook_signature(
            signature_header=bad_header, body=b"{}"
        )
        is False
    )


def test_webhook_signature_rejects_old_timestamp(monkeypatch):
    secret = "whsec_test_super_secret"
    monkeypatch.setattr(settings, "mux_webhook_secret", secret)

    body = b"{}"
    ts = str(int(time.time()) - 3600)  # 1h ago — past 5min window
    expected = hmac.new(
        secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    header = f"t={ts},v1={expected}"

    assert (
        mux_service.verify_webhook_signature(signature_header=header, body=body)
        is False
    )


def test_signing_health_reports_dev_state(monkeypatch):
    monkeypatch.setattr(settings, "mux_signing_key_id", "")
    monkeypatch.setattr(settings, "mux_signing_key_private", "")
    monkeypatch.setattr(settings, "mux_webhook_secret", "")
    health = mux_service.signing_health()
    assert health["signing_configured"] is False
    assert health["webhook_secret_present"] is False


def test_thumbnail_url_format():
    assert (
        mux_service.thumbnail_url("abc123", time_seconds=10)
        == "https://image.mux.com/abc123/thumbnail.jpg?time=10"
    )
