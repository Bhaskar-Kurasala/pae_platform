"""Tests for OAuth routes (GitHub and Google login flows)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# GET /auth/oauth/github
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_login_redirect_when_not_configured(client: AsyncClient) -> None:
    """With no GitHub client ID, the endpoint returns 503."""
    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.github_client_id = ""
        mock_settings.github_client_secret = ""
        resp = await client.get("/api/v1/auth/oauth/github", follow_redirects=False)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_github_login_redirects_to_provider(client: AsyncClient) -> None:
    """With a configured client ID, we get a redirect to GitHub."""
    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.github_client_id = "test_client_id"
        mock_settings.github_client_secret = "test_client_secret"
        resp = await client.get("/api/v1/auth/oauth/github", follow_redirects=False)

    assert resp.status_code == 302
    assert "github.com/login/oauth/authorize" in resp.headers["location"]
    assert "test_client_id" in resp.headers["location"]


# ---------------------------------------------------------------------------
# GET /auth/oauth/google
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_login_redirect_when_not_configured(client: AsyncClient) -> None:
    """With no Google client ID, the endpoint returns 503."""
    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.google_client_id = ""
        mock_settings.google_client_secret = ""
        resp = await client.get("/api/v1/auth/oauth/google", follow_redirects=False)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_google_login_redirects_to_provider(client: AsyncClient) -> None:
    """With a configured client ID, we get a redirect to Google."""
    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.google_client_id = "google_test_id"
        mock_settings.google_client_secret = "google_test_secret"
        resp = await client.get("/api/v1/auth/oauth/google", follow_redirects=False)

    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["location"]
    assert "google_test_id" in resp.headers["location"]


# ---------------------------------------------------------------------------
# GET /auth/oauth/github/callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_callback_not_configured_redirects_to_error(
    client: AsyncClient,
) -> None:
    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.github_client_id = ""
        mock_settings.github_client_secret = ""
        resp = await client.get(
            "/api/v1/auth/oauth/github/callback?code=fake_code",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=oauth_failed" in resp.headers["location"]


@pytest.mark.asyncio
async def test_github_callback_bad_token_exchange_redirects_to_error(
    client: AsyncClient,
) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error": "bad_verification_code"}

    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.github_client_id = "cid"
        mock_settings.github_client_secret = "csecret"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_ctx

            resp = await client.get(
                "/api/v1/auth/oauth/github/callback?code=bad_code",
                follow_redirects=False,
            )

    assert resp.status_code == 302
    assert "error=oauth_failed" in resp.headers["location"]


@pytest.mark.asyncio
async def test_github_callback_success_redirects_with_token(
    client: AsyncClient,
) -> None:
    """Successful GitHub OAuth flow upserts user and returns JWT in redirect."""
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "gho_abc123"}

    user_resp = MagicMock()
    user_resp.status_code = 200
    user_resp.json.return_value = {
        "id": 99999,
        "login": "octocat",
        "name": "The Octocat",
        "email": "octocat@github.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/583231",
    }

    emails_resp = MagicMock()
    emails_resp.status_code = 200
    emails_resp.json.return_value = [
        {"email": "octocat@github.com", "primary": True, "verified": True}
    ]

    call_count = 0

    async def _mock_post(*args: object, **kwargs: object) -> MagicMock:
        return token_resp

    async def _mock_get(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if "emails" in url:
            return emails_resp
        return user_resp

    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.github_client_id = "cid"
        mock_settings.github_client_secret = "csecret"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.post = _mock_post  # type: ignore[method-assign]
            mock_ctx.get = _mock_get  # type: ignore[method-assign]
            mock_client_cls.return_value = mock_ctx

            resp = await client.get(
                "/api/v1/auth/oauth/github/callback?code=good_code",
                follow_redirects=False,
            )

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "/dashboard" in location
    assert "token=" in location


# ---------------------------------------------------------------------------
# GET /auth/oauth/google/callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_callback_not_configured_redirects_to_error(
    client: AsyncClient,
) -> None:
    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.google_client_id = ""
        mock_settings.google_client_secret = ""
        resp = await client.get(
            "/api/v1/auth/oauth/google/callback?code=fake_code",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=oauth_failed" in resp.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_success_redirects_with_token(
    client: AsyncClient,
) -> None:
    """Successful Google OAuth flow upserts user and returns JWT in redirect."""
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "ya29.test_token"}

    userinfo_resp = MagicMock()
    userinfo_resp.status_code = 200
    userinfo_resp.json.return_value = {
        "sub": "google-uid-12345",
        "email": "testuser@gmail.com",
        "name": "Test Google User",
        "picture": "https://lh3.googleusercontent.com/test",
        "email_verified": True,
    }

    async def _mock_post(*args: object, **kwargs: object) -> MagicMock:
        return token_resp

    async def _mock_get(*args: object, **kwargs: object) -> MagicMock:
        return userinfo_resp

    with patch("app.api.v1.routes.oauth.settings") as mock_settings:
        mock_settings.google_client_id = "gcid"
        mock_settings.google_client_secret = "gcsecret"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.post = _mock_post  # type: ignore[method-assign]
            mock_ctx.get = _mock_get  # type: ignore[method-assign]
            mock_client_cls.return_value = mock_ctx

            resp = await client.get(
                "/api/v1/auth/oauth/google/callback?code=good_code",
                follow_redirects=False,
            )

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "/dashboard" in location
    assert "token=" in location
