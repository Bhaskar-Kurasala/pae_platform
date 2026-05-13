"""Tests for POST /auth/verify-email/resend (R1)."""

import uuid

from httpx import AsyncClient

RESEND_URL = "/api/v1/auth/verify-email/resend"


def _unique_email(prefix: str = "resend") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def test_resend_unknown_email_returns_202(client: AsyncClient) -> None:
    resp = await client.post(RESEND_URL, json={"email": "nobody_at_all@example.com"})
    assert resp.status_code == 202
    assert "message" in resp.json()


async def test_resend_unverified_user_returns_202(client: AsyncClient) -> None:
    email = _unique_email("unverified")
    await client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Resend User", "password": "TestPassword123!",
    })
    resp = await client.post(RESEND_URL, json={"email": email})
    assert resp.status_code == 202


async def test_resend_already_verified_user_returns_202(client: AsyncClient) -> None:
    # _auto_verify_registered_users autouse fixture auto-sets is_verified=True
    # for any user created via register, so this is a verified user by the time
    # we call resend — endpoint must still return 202 (no enumeration).
    email = _unique_email("verified")
    await client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Resend User", "password": "TestPassword123!",
    })
    resp = await client.post(RESEND_URL, json={"email": email})
    assert resp.status_code == 202


async def test_resend_response_has_no_pii(client: AsyncClient) -> None:
    email = "piicheck@example.com"
    resp = await client.post(RESEND_URL, json={"email": email})
    assert resp.status_code == 202
    body = resp.json()
    # Response must only contain a neutral message key — no user data leaked
    assert set(body.keys()) == {"message"}
    assert email not in body["message"]
    assert "token" not in body["message"]
    assert '"id"' not in body["message"]
