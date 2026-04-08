import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "student"


class UserUpdate(BaseModel):
    full_name: str | None = None
    github_username: str | None = None
    avatar_url: str | None = None


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    is_verified: bool
    github_username: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime
