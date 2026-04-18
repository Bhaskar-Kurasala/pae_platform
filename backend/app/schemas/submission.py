import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SubmissionCreate(BaseModel):
    exercise_id: uuid.UUID | None = None
    code: str | None = None
    github_pr_url: str | None = None
    # P2-07: opt-in sharing. Defaults to False — private unless the student
    # explicitly chooses to share.
    shared_with_peers: bool = False
    share_note: str | None = Field(default=None, max_length=500)


class SubmissionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    student_id: uuid.UUID
    exercise_id: uuid.UUID
    status: str
    score: int | None = None
    feedback: str | None = None
    ai_feedback: dict[str, Any] | None = None
    attempt_number: int
    shared_with_peers: bool = False
    share_note: str | None = None
    created_at: datetime
    updated_at: datetime


class PeerSubmissionItem(BaseModel):
    """One entry in the peer-solutions gallery (anonymized)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str | None
    share_note: str | None
    score: int | None
    created_at: datetime
    # Display handle — always a generated pseudonym ("peer_3fa7"), never the
    # real name or email. Gallery is anonymous by design.
    author_handle: str


class ShareUpdate(BaseModel):
    """Toggle sharing on an existing submission."""

    shared_with_peers: bool
    share_note: str | None = Field(default=None, max_length=500)
