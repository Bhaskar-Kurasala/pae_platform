"""PR3/D3.2 — refresh-token cookie hardening on /api/v1/auth.

Acceptance: the refresh-token cookie set on login (and rotated on
refresh) carries the four hardened flags:

  - HttpOnly      → JS can't read it (XSS-resistant)
  - SameSite=Lax  → cross-site POSTs can't replay it
  - Path=/api/v1/auth → not sent on any other API request
  - Secure        → set in production, off in dev (so localhost still works)

These tests exercise the live route via the standard `client` fixture,
poking at `Set-Cookie` headers directly.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def _register_and_login(
    client: AsyncClient, email: str
) -> tuple[dict[str, str], str]:
    """Helper: register a user, log in, return (login_json, raw_set_cookie)."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Cookie Tester",
            "password": "pass1234",
            "role": "student",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "pass1234"},
    )
    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie", "")
    return resp.json(), set_cookie


async def test_login_sets_refresh_token_cookie(client: AsyncClient) -> None:
    body, raw = await _register_and_login(client, "cookie-login@example.com")
    assert body["refresh_token"], "body still carries refresh_token for legacy callers"
    assert "refresh_token=" in raw, f"cookie not set in response: {raw!r}"


async def test_refresh_cookie_is_httponly(client: AsyncClient) -> None:
    _, raw = await _register_and_login(client, "cookie-httponly@example.com")
    # `HttpOnly` (case-insensitive) appears in the Set-Cookie header.
    assert "httponly" in raw.lower(), raw


async def test_refresh_cookie_is_samesite_lax(client: AsyncClient) -> None:
    _, raw = await _register_and_login(client, "cookie-samesite@example.com")
    assert "samesite=lax" in raw.lower(), raw


async def test_refresh_cookie_path_scoped_to_auth(client: AsyncClient) -> None:
    """The cookie must NOT be sent to non-auth API calls — that's the
    whole point of `Path=/api/v1/auth`."""
    _, raw = await _register_and_login(client, "cookie-path@example.com")
    assert "path=/api/v1/auth" in raw.lower(), raw
    # Negative: the cookie path is NOT root.
    assert "path=/;" not in raw.lower(), raw


async def test_refresh_cookie_not_secure_in_test_env(client: AsyncClient) -> None:
    """In dev/test, Secure must be OFF so the browser sends the cookie
    over plain http://localhost. Production_required (D2.2) ensures
    we can't ship Secure=False to prod since Secure is driven by
    `environment == 'production'`."""
    _, raw = await _register_and_login(client, "cookie-secure@example.com")
    # Pytest doesn't set ENVIRONMENT=production, so Secure must NOT
    # appear in the Set-Cookie header.
    assert "secure" not in raw.lower(), raw


async def test_refresh_endpoint_reads_cookie(client: AsyncClient) -> None:
    """The hardened cookie alone (no body field) is sufficient to
    refresh."""
    body, _ = await _register_and_login(client, "cookie-refresh-read@example.com")

    # Send refresh with an EMPTY body — relies entirely on the cookie
    # the prior login set on the client.
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": ""},
    )
    assert resp.status_code == 200, resp.text
    new_body = resp.json()
    assert new_body["access_token"]
    assert new_body["refresh_token"]
    # Cookie was rotated.
    rotated = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in rotated


async def test_refresh_endpoint_falls_back_to_body_when_no_cookie(
    client: AsyncClient,
) -> None:
    """Backward-compat: a frontend that hasn't migrated to cookies yet
    still works by passing the token in the body."""
    body, _ = await _register_and_login(client, "cookie-fallback@example.com")
    legacy_token = body["refresh_token"]

    # Drop the cookie jar so only the body carries the token.
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": legacy_token},
    )
    assert resp.status_code == 200, resp.text


async def test_logout_clears_cookie(client: AsyncClient) -> None:
    """`POST /auth/logout` deletes the cookie so a stolen device
    can't replay it."""
    await _register_and_login(client, "cookie-logout@example.com")
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    raw = resp.headers.get("set-cookie", "")
    # delete_cookie() emits a Set-Cookie with an empty value and
    # Max-Age=0 (or Expires in the past). The framework normalizes to
    # `refresh_token=""` with Max-Age=0.
    assert "refresh_token=" in raw, raw
    assert "max-age=0" in raw.lower() or "expires=" in raw.lower(), raw
