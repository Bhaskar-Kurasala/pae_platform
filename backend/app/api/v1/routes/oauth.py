# ADD TO main.py: from app.api.v1.routes.oauth import router as oauth_router
# ADD TO main.py: app.include_router(oauth_router, prefix="/api/v1")
"""OAuth routes for GitHub and Google authentication.

Uses httpx (already a declared dependency) for the OAuth token exchange and
user-profile fetches instead of authlib, which keeps the dependency footprint
minimal.  The flow for both providers is:

1. GET /auth/oauth/{provider}           -> redirect to provider authorisation URL
2. GET /auth/oauth/{provider}/callback  -> exchange code for token, upsert user,
                                           issue JWT, redirect to frontend
"""
import secrets
import urllib.parse
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.repositories.user_repository import UserRepository
from app.schemas.oauth import OAuthCallbackResponse, OAuthUserInfo

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])
log = structlog.get_logger()

# ── Constants ───────────────────────────────────────────────────────────────

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

_GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_FRONTEND_DASHBOARD = "http://localhost:3000/dashboard"
_FRONTEND_ERROR = "http://localhost:3000/login?error=oauth_failed"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _github_callback_url() -> str:
    return "http://localhost:8000/api/v1/auth/oauth/github/callback"


def _google_callback_url() -> str:
    return "http://localhost:8000/api/v1/auth/oauth/google/callback"


async def _upsert_oauth_user(db: AsyncSession, info: OAuthUserInfo) -> Any:
    """Find an existing user by email or create a new one (no password).

    Returns the User ORM object.
    """
    repo = UserRepository(db)
    user = await repo.get_by_email(info.email)
    if user:
        # Update OAuth-sourced fields.
        update_data: dict[str, Any] = {}
        if info.avatar_url and not user.avatar_url:
            update_data["avatar_url"] = info.avatar_url
        if info.github_username and not user.github_username:
            update_data["github_username"] = info.github_username
        if update_data:
            user = await repo.update(user, update_data)
        await db.commit()
        log.info("oauth.user_found", email=info.email, provider=info.provider)
        return user

    # Create a new user without a password — OAuth-only account.
    user = await repo.create(
        {
            "email": info.email,
            "full_name": info.name or info.email.split("@")[0],
            "hashed_password": None,  # No password for OAuth users
            "role": "student",
            "is_active": True,
            "is_verified": True,  # Provider already verified the email
            "avatar_url": info.avatar_url,
            "github_username": info.github_username,
        }
    )
    await db.commit()
    log.info("oauth.user_created", email=info.email, provider=info.provider)
    return user


# ── GitHub ───────────────────────────────────────────────────────────────────


@router.get("/github")
async def github_login() -> RedirectResponse:
    """Redirect the browser to GitHub's OAuth authorisation page."""
    if not settings.github_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured",
        )

    state = secrets.token_urlsafe(16)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": _github_callback_url(),
        "scope": "read:user user:email",
        "state": state,
    }
    url = f"{_GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/github/callback", response_model=OAuthCallbackResponse)
async def github_callback(
    code: str = Query(...),
    state: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the GitHub OAuth callback, issue a JWT, and redirect to the dashboard."""
    if not settings.github_client_id or not settings.github_client_secret:
        log.error("oauth.github.not_configured")
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    async with httpx.AsyncClient() as client:
        # Exchange the authorisation code for an access token.
        token_resp = await client.post(
            _GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": _github_callback_url(),
            },
        )

    if token_resp.status_code != 200:
        log.warning("oauth.github.token_exchange_failed", status=token_resp.status_code)
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    token_data = token_resp.json()
    access_token: str | None = token_data.get("access_token")
    if not access_token:
        log.warning("oauth.github.no_access_token", response=token_data)
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    # Fetch the GitHub user profile.
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(_GITHUB_USER_URL, headers=headers)
        emails_resp = await client.get(_GITHUB_EMAILS_URL, headers=headers)

    if user_resp.status_code != 200:
        log.warning("oauth.github.user_fetch_failed", status=user_resp.status_code)
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    gh_user = user_resp.json()
    email: str | None = gh_user.get("email")

    # Primary email may be null on the profile — fall back to the emails API.
    if not email and emails_resp.status_code == 200:
        for entry in emails_resp.json():
            if entry.get("primary") and entry.get("verified"):
                email = entry.get("email")
                break

    if not email:
        log.warning("oauth.github.no_email", github_id=gh_user.get("id"))
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    info = OAuthUserInfo(
        email=email,
        name=gh_user.get("name") or gh_user.get("login") or email,
        provider="github",
        provider_user_id=str(gh_user.get("id", "")),
        avatar_url=gh_user.get("avatar_url"),
        github_username=gh_user.get("login"),
    )

    try:
        user = await _upsert_oauth_user(db, info)
    except Exception as exc:
        log.error("oauth.github.db_error", error=str(exc))
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    jwt_token = create_access_token({"sub": str(user.id), "role": user.role})
    redirect_url = f"{_FRONTEND_DASHBOARD}?token={jwt_token}"
    log.info("oauth.github.success", user_id=str(user.id))
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


# ── Google ────────────────────────────────────────────────────────────────────


@router.get("/google")
async def google_login() -> RedirectResponse:
    """Redirect the browser to Google's OAuth authorisation page."""
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )

    state = secrets.token_urlsafe(16)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _google_callback_url(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
    }
    url = f"{_GOOGLE_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback", response_model=OAuthCallbackResponse)
async def google_callback(
    code: str = Query(...),
    state: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the Google OAuth callback, issue a JWT, and redirect to the dashboard."""
    if not settings.google_client_id or not settings.google_client_secret:
        log.error("oauth.google.not_configured")
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _google_callback_url(),
            },
        )

    if token_resp.status_code != 200:
        log.warning("oauth.google.token_exchange_failed", status=token_resp.status_code)
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    token_data = token_resp.json()
    google_access_token: str | None = token_data.get("access_token")
    if not google_access_token:
        log.warning("oauth.google.no_access_token", response=token_data)
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    # Fetch the Google user info.
    async with httpx.AsyncClient() as client:
        userinfo_resp = await client.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )

    if userinfo_resp.status_code != 200:
        log.warning("oauth.google.userinfo_failed", status=userinfo_resp.status_code)
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    userinfo = userinfo_resp.json()
    email: str | None = userinfo.get("email")
    if not email:
        log.warning("oauth.google.no_email", sub=userinfo.get("sub"))
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    info = OAuthUserInfo(
        email=email,
        name=userinfo.get("name") or email,
        provider="google",
        provider_user_id=str(userinfo.get("sub", "")),
        avatar_url=userinfo.get("picture"),
    )

    try:
        user = await _upsert_oauth_user(db, info)
    except Exception as exc:
        log.error("oauth.google.db_error", error=str(exc))
        return RedirectResponse(url=_FRONTEND_ERROR, status_code=302)

    jwt_token = create_access_token({"sub": str(user.id), "role": user.role})
    redirect_url = f"{_FRONTEND_DASHBOARD}?token={jwt_token}"
    log.info("oauth.google.success", user_id=str(user.id))
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
