from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    PasswordResetConfirmPayload,
    PasswordResetRequestPayload,
    RefreshRequest,
    RegisterResponse,
    ResendVerificationRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


# PR3/D3.2 — Cookie name + path for the hardened refresh-token cookie.
# Path is intentionally scoped to `/api/v1/auth` so the cookie is only
# attached to auth requests — every other API call (which trips through
# `Authorization: Bearer …`) won't carry the long-lived refresh token,
# minimizing CSRF + token-leak surface.
_REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _is_production() -> bool:
    """Return True iff we're running in production. Drives the `Secure`
    cookie flag — local dev over plain http://localhost would otherwise
    have the cookie silently rejected by the browser."""
    return settings.environment.lower() == "production"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Stamp the hardened refresh-token cookie on a response.

    Flags (PR3/D3.2 acceptance criteria):
      - HttpOnly: JavaScript cannot read it → XSS can't exfiltrate it.
      - Secure: only sent over HTTPS in production. Disabled in dev so
        local http://localhost flows still work; the production_required
        validator (PR3/D2.2) ensures we don't accidentally ship `Secure=False`
        to prod since the env check drives this branch.
      - SameSite=Lax: blocks cross-site POSTs that would silently use
        the cookie. Lax (not Strict) so a top-level navigation from an
        email link still authenticates.
      - Path=/api/v1/auth: the cookie is only sent to the auth endpoints.
        Every other API call uses Bearer access tokens.
    """
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=_is_production(),
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Remove the hardened refresh-token cookie. Used on logout AND on
    any 401-from-refresh path so a stale token isn't left in the
    browser jar."""
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=_is_production(),
        samesite="lax",
    )


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


@router.post("/register", response_model=RegisterResponse, status_code=202)
@limiter.limit("10/minute")
async def register(
    request: Request,
    payload: UserCreate,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """D-B: Always returns 202 with a neutral message — never reveals whether
    the email is new or already registered (enumeration prevention)."""
    return await service.register(payload)


@router.post("/verify-email", response_model=RegisterResponse, status_code=200)
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    payload: VerifyEmailRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """A2: Consume an email_verify token and mark the account as verified."""
    return await service.verify_email(payload.token)


@router.post("/verify-email/resend", response_model=RegisterResponse, status_code=202)
@limiter.limit("5/minute")
async def verify_email_resend(
    request: Request,
    payload: ResendVerificationRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """R1: Always 202 — neutral message prevents email enumeration."""
    return await service.resend_verification_email(payload.email)


@router.post("/password-reset/request", response_model=RegisterResponse, status_code=202)
@limiter.limit("5/minute")
async def password_reset_request(
    request: Request,
    payload: PasswordResetRequestPayload,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """A1: Always 202 — neutral message prevents email enumeration."""
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    return await service.request_password_reset(payload.email, ip_address=ip)


@router.post("/password-reset/confirm", response_model=RegisterResponse, status_code=200)
@limiter.limit("10/minute")
async def password_reset_confirm(
    request: Request,
    payload: PasswordResetConfirmPayload,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """A1: Validate reset token and set new password."""
    return await service.confirm_password_reset(payload.token, payload.new_password)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    tokens = await service.login(payload.email, payload.password)
    # PR3/D3.2 — also stamp the refresh token as a hardened cookie.
    # Body still carries `refresh_token` for backwards-compat with the
    # current frontend localStorage flow; once the frontend migrates to
    # cookie-only refresh, we drop the body field in a follow-up.
    _set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("60/minute")
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    # PR3/D3.2 — accept the refresh token from EITHER the request body
    # (legacy) OR the hardened cookie. Cookie wins when both are
    # present, since it's the more secure source.
    cookie_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    token = cookie_token or payload.refresh_token
    tokens = await service.refresh(token)
    _set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    """Clear the hardened refresh-token cookie. Idempotent — safe to
    call without a session.

    PR3/D3.2: introduced alongside the cookie hardening so the frontend
    has a server-side hook to invalidate the cookie on sign-out. The
    access token is short-lived (8h default) and is not server-side
    invalidated — that's a JWT property, not a regression."""
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
