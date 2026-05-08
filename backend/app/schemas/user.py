import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "student"
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
