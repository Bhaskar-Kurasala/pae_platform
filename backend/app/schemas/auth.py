from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.user import _COMMON_PASSWORDS


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    # PR3/D3.2 — optional now: when the hardened refresh cookie is
    # present, the route reads the token from the cookie and ignores
    # this body field. Body is still accepted for the legacy
    # localStorage frontend flow until that's migrated.
    refresh_token: str = ""


class RegisterResponse(BaseModel):
    message: str


class VerifyEmailRequest(BaseModel):
    token: str


class PasswordResetRequestPayload(BaseModel):
    email: EmailStr


class PasswordResetConfirmPayload(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if v.lower() in _COMMON_PASSWORDS:
            raise ValueError("Password is too common")
        return v


class ResendVerificationRequest(BaseModel):
    email: EmailStr
