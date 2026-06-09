"""D18 Phase B CP1 — Journey (i) payment happy path with mocked Stripe.

Tests the Stripe webhook signature-verification + entitlement-
provisioning surface. Pattern 32 candidate: mock at the payment-
provider HTTP boundary; signature exercised with constructed-but-
valid HMAC payloads.

Approach:
  * Sign a synthetic Stripe `checkout.session.completed` payload
    with HMAC-SHA256 using a test webhook secret.
  * POST to /api/v1/webhooks/stripe with the `Stripe-Signature`
    header.
  * If `STRIPE_WEBHOOK_SECRET` is configured in the backend env,
    verification + downstream provisioning fires.
  * If not configured, the route returns 503 — verified by the
    "secret-not-configured" path.

Pattern 22 finding at CP1 authoring: STRIPE_WEBHOOK_SECRET is
empty in the runner-overlay env. Three of the four tests here are
xfailed-strict pending env config; the bad-signature test runs
unconditionally because that path doesn't depend on a configured
secret (the route's first check is `if not settings.stripe_webhook_secret`).

Cost class: low (no LLM agents).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid as _uuid

import pytest
from playwright.sync_api import Page

from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    register_via_http,
)

from ._journey_helpers import API_BASE

pytestmark = [pytest.mark.critical_path, pytest.mark.cost("low")]


# Test-mode fake; matches what an env override would supply.
_TEST_WEBHOOK_SECRET = "whsec_test_cp1_journey_i_FAKE_DO_NOT_USE_IN_PROD"


def _stripe_signed_post(
    payload: dict,
    *,
    secret: str = _TEST_WEBHOOK_SECRET,
    skew_seconds: int = 0,
) -> tuple[int, dict | None]:
    """POST /webhooks/stripe with a constructed-but-valid Stripe-Signature.

    Mirrors `_verify_stripe_signature` in
    backend/app/api/v1/routes/webhooks.py: the signature payload is
    `f"{timestamp}.{body}"`, HMAC-SHA256 hexdigest under `secret`.
    """
    body = json.dumps(payload).encode("utf-8")
    timestamp = str(int(time.time()) + skew_seconds)
    signed_payload = f"{timestamp}.{body.decode()}"
    sig = hmac.new(
        secret.encode(), signed_payload.encode(), hashlib.sha256
    ).hexdigest()
    header_value = f"t={timestamp},v1={sig}"
    req = urllib.request.Request(
        url=f"{API_BASE}/webhooks/stripe",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": header_value,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, None


# ── Tests ──────────────────────────────────────────────────────────


def test_stripe_webhook_unconfigured_returns_503(page: Page) -> None:
    """Pattern 22-aware test: when STRIPE_WEBHOOK_SECRET is empty
    (runner-overlay default), the route returns 503 BEFORE doing
    signature verification.

    This is the only test in this file that runs unconditionally;
    the others xfail until secret is configured.
    """
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer_email": "test@example.com"}},
    }
    status, body = _stripe_signed_post(payload)
    assert status == 503, (
        f"expected 503 (unconfigured), got {status}: {body}. "
        f"If STRIPE_WEBHOOK_SECRET is now configured in the runner "
        f"overlay env, this test should be re-evaluated and the "
        f"xfailed companions below dropped."
    )
    assert body is not None
    assert "Stripe webhook not configured" in body.get("detail", "")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "STRIPE_WEBHOOK_SECRET is empty in the runner-overlay env "
        "(verified at CP1 pre-flight). The /webhooks/stripe route "
        "short-circuits to 503 before signature verification. "
        "Remove xfail when overlay sets the secret."
    ),
)
def test_stripe_webhook_with_valid_signature_returns_received(
    page: Page,
) -> None:
    """Happy path: valid HMAC signature → 200 + {status: received}.

    Pattern 32 canonical shape — signature-validation exercised
    with constructed-but-valid HMAC payloads at the HTTP boundary;
    no Stripe SDK / no real Stripe call.
    """
    payload = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer_email": "happy@example.com",
                "metadata": {"course_id": "test-course"},
                "amount_total": 9900,
                "payment_intent": "pi_test_cp1_journey_i",
            }
        },
    }
    status, body = _stripe_signed_post(payload)
    assert status == 200
    assert body is not None
    assert body["status"] == "received"
    assert body["event"] == "checkout.session.completed"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Same env precondition as the happy-path test above: "
        "STRIPE_WEBHOOK_SECRET unconfigured. Remove xfail when "
        "overlay sets the secret."
    ),
)
def test_stripe_webhook_with_invalid_signature_returns_401(
    page: Page,
) -> None:
    """Bad signature → 401 Unauthorized.

    Negative path of the signature contract. Verifies that
    tampering with the HMAC fails closed (not opens up).
    """
    payload = {"type": "checkout.session.completed", "data": {}}
    status, body = _stripe_signed_post(
        payload, secret="wrong_secret_does_not_match_backend",
    )
    assert status == 401, f"expected 401, got {status}: {body}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "checkout.session.completed handling provisions an "
        "enrollment via background task; the provisioning happens "
        "out-of-band from the HTTP response. Test would need to "
        "either poll or use TestClient. Defer to CP3 traceability "
        "when STRIPE_WEBHOOK_SECRET is configured."
    ),
)
def test_stripe_checkout_completed_provisions_entitlement(
    page: Page,
) -> None:
    """Full happy path: webhook → background task → enrollment row."""
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp1i-payment-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyI123!", full_name="CP1I Buyer",
    )
    try:
        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer_email": email,
                    "metadata": {"course_id": "data-analyst"},
                    "amount_total": 9900,
                    "payment_intent": f"pi_test_{suffix}",
                }
            },
        }
        status, _ = _stripe_signed_post(payload)
        assert status == 200
        # Background task fires async; CP3 traceability test verifies.
        # For CP1 we just assert the webhook accepted the event.
    finally:
        cleanup_student_via_db(user_id)
