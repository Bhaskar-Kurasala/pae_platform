import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hashing import hash_password, verify_password
from app.core.security import create_access_token, create_refresh_token, verify_token
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate

log = structlog.get_logger()


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = UserRepository(db)

    async def register(self, payload: UserCreate) -> User:
        existing = await self.repo.get_by_email(payload.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        user = await self.repo.create(
            {
                "email": payload.email,
                "full_name": payload.full_name,
                "hashed_password": hash_password(payload.password),
                "role": payload.role,
            }
        )
        log.info("auth.register", user_id=str(user.id))

        # Emit a real cohort_event so the admin "Live event feed" on
        # /admin lights up immediately when a student signs up. Only
        # emitted for role=student — admin/instructor signups don't
        # belong in the cohort feed.
        if user.role == "student":
            try:
                from app.services.cohort_event_service import (
                    mask_handle,
                    record_event,
                )

                await record_event(
                    self.repo.db,
                    kind="signup",
                    actor=user,
                    label=f"{mask_handle(user.full_name)} joined the cohort",
                )
            except Exception as exc:  # noqa: BLE001
                # Cohort emission must never block registration; log
                # and move on.
                log.warning(
                    "auth.cohort_event_failed",
                    user_id=str(user.id),
                    error=str(exc),
                )

        # D10 Checkpoint 3 — grant a 24-hour signup_grace free-tier
        # window per Pass 3f §C.1. Function shipped in D9 but was
        # never called from production registration (deferred Item 11
        # from D9 closure). Without this hook, freshly-signed-up
        # students get 402 from the canonical agentic endpoint
        # because compute_active_entitlements sees no active
        # entitlement AND no free-tier grant.
        #
        # Student-role-only mirrors the cohort_event filter above —
        # admins / instructors authenticate via different paths and
        # don't need the signup_grace UX. Idempotent (the function
        # returns the existing grant id if one is already active),
        # so a repeat call from a future flow doesn't stack grants.
        # Best-effort like the cohort_event block: failure to grant
        # must never block registration.
        if user.role == "student":
            try:
                from app.services.entitlement_service import grant_signup_grace

                await grant_signup_grace(self.repo.db, user_id=user.id)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "auth.signup_grace_failed",
                    user_id=str(user.id),
                    error=str(exc),
                )

        return user

    async def login(self, email: str, password: str) -> dict[str, str]:
        user = await self.repo.get_by_email(email)
        if not user or not user.hashed_password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        if not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account disabled",
            )
        access_token = create_access_token({"sub": str(user.id), "role": user.role})
        refresh_token = create_refresh_token({"sub": str(user.id)})
        log.info("auth.login", user_id=str(user.id))
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    async def refresh(self, refresh_token: str) -> dict[str, str]:
        payload = verify_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token payload",
            )
        user = await self.repo.get(uuid.UUID(user_id))
        if not user or user.is_deleted or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or disabled",
            )
        new_access = create_access_token({"sub": str(user.id), "role": user.role})
        new_refresh = create_refresh_token({"sub": str(user.id)})
        log.info("auth.refresh", user_id=str(user.id))
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
        }
