"""Pydantic schemas for the readiness diagnostic API.

Mirrors the data models in ``app/models/readiness.py`` but exposes only the
shape the frontend needs. The diagnostic surface is conversational so the
schemas are turn-oriented: start a session → send a turn → finalize → read
verdict.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceKind = Literal["strength", "gap", "neutral"]
TurnRole = Literal["student", "agent"]
SessionStatus = Literal[
    "active", "finalizing", "completed", "abandoned"
]
NextActionIntent = Literal[
    "skills_gap",
    "story_gap",
    "interview_gap",
    "jd_target_unclear",
    "ready_but_stalling",
    "thin_data",
    "ready_to_apply",
]


class EvidenceChip(BaseModel):
    """One claim in a verdict or match-score, traceable to the snapshot.

    ``evidence_id`` MUST appear in the paired snapshot's
    ``evidence_allowlist`` — otherwise the validator rejects the parent
    output and triggers a regenerate.
    """

    text: str = Field(..., min_length=1, max_length=240)
    evidence_id: str = Field(..., min_length=1, max_length=120)
    kind: EvidenceKind
    source_url: str | None = None


class NextAction(BaseModel):
    intent: NextActionIntent
    route: str = Field(..., max_length=255)
    label: str = Field(..., max_length=120)


class VerdictPayload(BaseModel):
    """The structured output of the VerdictGenerator."""

    headline: str = Field(..., min_length=1, max_length=280)
    evidence: list[EvidenceChip] = Field(..., min_length=1, max_length=6)
    next_action: NextAction


class StartDiagnosticResponse(BaseModel):
    session_id: uuid.UUID
    opening_message: str
    snapshot_summary: dict[str, Any]
    prior_session_hint: str | None = None


class TurnRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class TurnResponse(BaseModel):
    session_id: uuid.UUID
    turn: int
    agent_message: str
    is_final: bool = False
    invoke_jd_decoder: bool = False


class FinalizeRequest(BaseModel):
    """Optional override hints — students who hit the soft cap mid-thought
    can pass a last note before finalize.
    """

    closing_note: str | None = Field(default=None, max_length=2000)


class FinalizeResponse(BaseModel):
    session_id: uuid.UUID
    verdict: VerdictPayload
    sycophancy_flags: list[str] = Field(default_factory=list)


class PastDiagnosis(BaseModel):
    session_id: uuid.UUID
    started_at: datetime
    completed_at: datetime | None
    headline: str | None
    next_action_label: str | None
    next_action_intent: NextActionIntent | None
    next_action_clicked_at: datetime | None
    next_action_completed_at: datetime | None


class PastDiagnosesResponse(BaseModel):
    items: list[PastDiagnosis]


class NextActionClickRequest(BaseModel):
    session_id: uuid.UUID


class NextActionClickResponse(BaseModel):
    session_id: uuid.UUID
    clicked_at: datetime


class CompletionCheckResponse(BaseModel):
    session_id: uuid.UUID
    clicked_at: datetime | None
    completed_at: datetime | None
    completed_within_window: bool
    intent: NextActionIntent | None


class NorthStarRateResponse(BaseModel):
    window_days: int
    sessions_with_verdict: int
    sessions_clicked: int
    sessions_completed_within_24h: int
    click_through_rate: float
    completion_within_24h_rate: float
