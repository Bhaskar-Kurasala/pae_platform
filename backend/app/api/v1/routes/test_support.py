"""Test-support routes.

SECURITY: This router is only mounted when settings.environment != "production".
It exposes internal token creation for journey tests. Never ship to production.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.auth_token import TokenType
from app.repositories.auth_token_repository import AuthTokenRepository
from app.repositories.user_repository import UserRepository

router = APIRouter(prefix="/auth/test-support", tags=["test-support"])


@router.get("/latest-token")
async def get_latest_token(
    email: str,
    token_type: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create a new auth token for the given user and return the raw value.

    PATH 1: create token + return raw. Raw tokens are never stored (only
    SHA256 hash), so retrieval of an existing raw token is impossible.
    This endpoint is the only way to get a raw token in tests without
    access to the email inbox.

    Only mounted when settings.environment != 'production'.
    """
    user_repo = UserRepository(db)
    token_repo = AuthTokenRepository(db)

    user = await user_repo.get_by_email(email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        token_type_enum = TokenType(token_type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown token_type: {token_type}")

    raw_token, _record = await token_repo.create_token(user.id, token_type_enum)
    return {"raw_token": raw_token}
