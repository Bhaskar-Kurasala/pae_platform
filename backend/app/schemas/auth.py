from pydantic import BaseModel, EmailStr


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
