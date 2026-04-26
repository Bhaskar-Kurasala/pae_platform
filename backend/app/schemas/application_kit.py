"""Pydantic schemas for the Application Kit endpoint surface.

The kit is a snapshot bundle: resume + tailored variant + JD + mock interview
report + portfolio autopsy, frozen into a manifest dict and rendered to PDF.
The schemas here mirror the route surface — list rows are deliberately thin
(no manifest payload), detail rows carry the full snapshot.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BuildKitRequest(BaseModel):
    """Body for `POST /readiness/kit` — all source-row refs are optional."""

    label: str = Field(..., min_length=1, max_length=120)
    target_role: str | None = Field(default=None, max_length=120)
    jd_library_id: uuid.UUID | None = None
    tailored_resume_id: uuid.UUID | None = None
    mock_session_id: uuid.UUID | None = None
    autopsy_id: uuid.UUID | None = None


class ApplicationKitListItem(BaseModel):
    """Lightweight row for the index view — omits the full manifest."""

    id: uuid.UUID
    label: str
    target_role: str | None = None
    status: str
    generated_at: datetime | None = None
    created_at: datetime
    manifest_keys: list[str] = Field(default_factory=list)


class ApplicationKitResponse(BaseModel):
    """Detail view — includes the resolved manifest snapshot."""

    id: uuid.UUID
    label: str
    target_role: str | None = None
    status: str
    generated_at: datetime | None = None
    created_at: datetime
    manifest: dict[str, Any] = Field(default_factory=dict)
    has_pdf: bool = False
