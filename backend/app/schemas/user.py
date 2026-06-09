import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

# D-D: common passwords — top-20 list; full check deferred to cohort-2 wordlist import.
_COMMON_PASSWORDS = frozenset(
    {
        "password123456",
        "password1234",
        "password123",
        "123456789012",
        "qwertyuiop12",
        "iloveyou1234",
        "welcome12345",
        "letmein12345",
        "sunshine1234",
        "princess1234",
        "football1234",
        "shadow123456",
        "monkey123456",
        "dragon123456",
        "master123456",
        "superman1234",
        "batman123456",
        "trustno11234",
        "starwars1234",
    }
)


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "student"

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if v.lower() in _COMMON_PASSWORDS:
            raise ValueError("Password is too common; choose a stronger one")
        return v
    # D16/CP3.1 — optional manual-WhatsApp outreach destination. E.164
    # format recommended (e.g. "+919876543210") but not validated in v1:
    # admins source numbers from existing channels and over-strict
    # validation would block valid edge cases (extensions, transient
    # re-keys mid-onboarding). Empty/None means no WhatsApp deep-link
    # rendered on the admin cockpit per-student panel.
    whatsapp_number: str | None = Field(
        default=None,
        description="Optional WhatsApp number, E.164 format recommended (e.g. +919876543210)",
    )


class UserUpdate(BaseModel):
    full_name: str | None = None
    github_username: str | None = None
    avatar_url: str | None = None
    # D16/CP3.1 — admin can backfill via this field on
    # PATCH /api/v1/admin/students/{id} (or a future per-user self-update).
    whatsapp_number: str | None = None


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
    # D16/CP3.1 — exposed on admin views so the cockpit can render the
    # wa.me deep link. Student-facing response is identical (it's the
    # student's own data); no PII concern that isn't already implied
    # by self-reporting at signup.
    whatsapp_number: str | None = None
    created_at: datetime
    updated_at: datetime
