import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hashing import hash_password, verify_password
from app.core.security import create_access_token, create_refresh_token, verify_token
from app.models.auth_token import TOKEN_TTL, AuthToken, TokenType
from app.models.user import User
from app.repositories.auth_token_repository import AuthTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.email_service import EmailService, check_email_rate_limit

log = structlog.get_logger()


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = UserRepository(db)
        self.token_repo = AuthTokenRepository(db)
        self.email_svc = EmailService()

    async def register(self, payload: UserCreate) -> dict[str, str]:
        """D-B: always 202; three branches — new user / conflict / disabled.

        Branch 1 (new user): create account, send verification email, return 202.
        Branch 2 (conflict, active): send account_exists email, return 202.
        Branch 3 (conflict, soft-deleted): treat as new (edge case — soft-delete
          means the user data is still there; we don't resurrect, just surface the
          account_exists flow so we don't leak deletion state).
        """
        existing = await self.repo.get_by_email(payload.email)

        if existing:
            # Branch 2/3 — email already registered; don't reveal that.
            self._record_auth_event("signup_conflict")
            rate_ok = await check_email_rate_limit(str(existing.id), TokenType.email_verify)
            if rate_ok:
                await self.email_svc.send_account_exists(
                    payload.email, existing.full_name, existing.id
                )
            return {"message": "If that address is new, you'll receive a verification email shortly."}

        # Branch 1 — new registration
        create_payload = {
            "email": payload.email,
            "full_name": payload.full_name,
            "hashed_password": hash_password(payload.password),
            "role": payload.role,
            "is_verified": False,
        }
        if payload.whatsapp_number:
            create_payload["whatsapp_number"] = payload.whatsapp_number
        user = await self.repo.create(create_payload)
        log.info("auth.register", user_id=str(user.id))
        self._record_auth_event("signup")

        # Side-effect 1: cohort_event (student only, best-effort)
        if user.role == "student":
            try:
                from app.services.cohort_event_service import mask_handle, record_event

                await record_event(
                    self.repo.db,
                    kind="signup",
                    actor=user,
                    label=f"{mask_handle(user.full_name)} joined the cohort",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("auth.cohort_event_failed", user_id=str(user.id), error=str(exc))

        # Side-effect 2: grant_signup_grace (student only, best-effort)
        if user.role == "student":
            try:
                from app.services.entitlement_service import grant_signup_grace

                await grant_signup_grace(self.repo.db, user_id=user.id)
            except Exception as exc:  # noqa: BLE001
                log.warning("auth.signup_grace_failed", user_id=str(user.id), error=str(exc))

        # Side-effect 3: send verification email (best-effort — don't block registration)
        try:
            rate_ok = await check_email_rate_limit(str(user.id), TokenType.email_verify)
            if rate_ok:
                raw_token, _record = await self.token_repo.create_token(
                    user_id=user.id, token_type=TokenType.email_verify
                )
                await self.email_svc.send_email_verification(
                    user.email, user.full_name, raw_token, user.id
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("auth.verify_email_send_failed", user_id=str(user.id), error=str(exc))

        return {"message": "If that address is new, you'll receive a verification email shortly."}

    async def verify_email(self, raw_token: str) -> dict[str, str]:
        """A2: consume an email_verify token and set is_verified=True."""
        record = await self.token_repo.get_by_hash(raw_token)
        if not record or record.token_type != TokenType.email_verify:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        if not record.is_valid():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

        user = await self.repo.get(record.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

        await self.token_repo.mark_used(record)
        if not user.is_verified:
            user.is_verified = True
            await self.repo.db.flush()

        log.info("auth.email_verified", user_id=str(user.id))
        return {"message": "Email verified. You can now log in."}

    async def resend_verification_email(self, email: str) -> dict[str, str]:
        """R1: always 202 — neutral message prevents email enumeration.

        Branch 1 (not found): return neutral.
        Branch 2 (already verified): return neutral (no token created).
        Branch 3 (rate-limited): return neutral.
        Branch 4 (unverified, within rate limit): create token, return neutral.
        SendGrid is not wired in this environment, so the email send is skipped;
        the token is created so the flow is testable end-to-end once email is wired.
        """
        _neutral = {"message": "If this email is registered and unverified, a new verification link has been sent."}
        user = await self.repo.get_by_email(email)
        if not user or user.is_deleted:
            return _neutral
        if user.is_verified:
            return _neutral

        rate_ok = await check_email_rate_limit(str(user.id), TokenType.email_verify)
        if not rate_ok:
            return _neutral

        _raw_token, _record = await self.token_repo.create_token(
            user_id=user.id, token_type=TokenType.email_verify
        )
        log.info("auth.verify_email_resent", user_id=str(user.id))
        return _neutral

    async def request_password_reset(self, email: str, ip_address: str | None = None) -> dict[str, str]:
        """A1: always 202; rate-limited token creation + email send."""
        _neutral = {"message": "If that email is registered, a reset link has been sent."}
        user = await self.repo.get_by_email(email)
        if not user or user.is_deleted:
            return _neutral

        rate_ok = await check_email_rate_limit(str(user.id), TokenType.password_reset)
        if not rate_ok:
            return _neutral

        raw_token, _record = await self.token_repo.create_token(
            user_id=user.id, token_type=TokenType.password_reset, ip_address=ip_address
        )
        await self.email_svc.send_password_reset_email(user.email, user.full_name, raw_token, user.id)
        log.info("auth.password_reset_requested", user_id=str(user.id))
        return _neutral

    async def confirm_password_reset(self, raw_token: str, new_password: str) -> dict[str, str]:
        """A1: validate token, set new password, reset lockout counters."""
        from app.schemas.user import UserCreate  # reuse D-D validator

        # Validate new password complexity via Pydantic (raises ValidationError → 422)
        UserCreate.model_validate(
            {"email": "x@x.com", "full_name": "x", "password": new_password}
        )

        record = await self.token_repo.get_by_hash(raw_token)
        if not record or record.token_type != TokenType.password_reset:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        if not record.is_valid():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

        user = await self.repo.get(record.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

        await self.token_repo.mark_used(record)
        user.hashed_password = hash_password(new_password)
        user.record_successful_login()  # resets failed_login_count + locked_until
        await self.repo.db.flush()

        log.info("auth.password_reset_confirmed", user_id=str(user.id))
        return {"message": "Password updated. You can now log in."}

    async def login(self, email: str, password: str) -> dict[str, str]:
        """D-C: check lockout → verify password → check is_verified → issue tokens."""
        user = await self.repo.get_by_email(email)
        if not user or not user.hashed_password:
            self._record_auth_event("login_failure")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        # D-C: lockout check before password verification to prevent timing oracle
        if user.is_locked():
            self._record_auth_event("login_failure")
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account temporarily locked due to too many failed attempts. Try again later.",
            )

        if not verify_password(password, user.hashed_password):
            user.record_failed_login()
            # Commit before raising so the counter persists — HTTPException
            # triggers the session's except branch (rollback) otherwise.
            await self.repo.db.commit()
            self._record_auth_event("login_failure")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        if not user.is_active:
            self._record_auth_event("login_disabled")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account disabled",
            )

        # A2: verification gate (grandfathered users have is_verified=True via migration 0069)
        if not user.is_verified:
            self._record_auth_event("login_failure")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Check your inbox or request a new verification link.",
            )

        user.record_successful_login()
        await self.repo.db.flush()

        access_token = create_access_token({"sub": str(user.id), "role": user.role})
        refresh_token = create_refresh_token({"sub": str(user.id)})
        log.info("auth.login", user_id=str(user.id))
        self._record_auth_event("login")
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
        self._record_auth_event("refresh")
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
        }

    @staticmethod
    def _record_auth_event(event_type: str) -> None:
        try:
            from app.core.metrics import AUTH_EVENTS

            AUTH_EVENTS.labels(event_type=event_type).inc()
        except Exception:  # noqa: BLE001
            pass
