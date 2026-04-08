import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hashing import hash_password, verify_password
from app.core.security import create_access_token, create_refresh_token
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
