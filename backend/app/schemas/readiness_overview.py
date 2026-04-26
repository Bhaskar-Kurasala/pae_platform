"""Readiness Overview + Proof Portfolio aggregator schemas.

The Job Readiness workspace's Overview view replaces a 100% hard-coded
KPI block with one signal-driven payload. Proof Portfolio replaces a
trio of placeholder cards with a real artifact list. Both views read
from a single aggregator each — the schemas here describe the wire
shape both aggregators emit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared sub-payloads
# ---------------------------------------------------------------------------


class SubScores(BaseModel):
    skill: int = Field(0, ge=0, le=100)
    proof: int = Field(0, ge=0, le=100)
    interview: int = Field(0, ge=0, le=100)
    targeting: int = Field(0, ge=0, le=100)


class NorthStarDelta(BaseModel):
    current: int = 0
    prior: int = 0
    delta_week: int = 0


class NextAction(BaseModel):
    kind: str
    route: str
    label: str
    payload: dict[str, Any] | None = None


class LatestVerdict(BaseModel):
    session_id: uuid.UUID
    headline: str
    next_action: NextAction
    created_at: datetime


class TrendPoint(BaseModel):
    week_start: date
    score: int


# ---------------------------------------------------------------------------
# Overview response
# ---------------------------------------------------------------------------


class OverviewResponse(BaseModel):
    user_first_name: str = ""
    target_role: str | None = None
    overall_readiness: int = Field(0, ge=0, le=100)
    sub_scores: SubScores = Field(default_factory=SubScores)
    north_star: NorthStarDelta = Field(default_factory=NorthStarDelta)
    top_actions: list[NextAction] = Field(default_factory=list)
    latest_verdict: LatestVerdict | None = None
    trend_8w: list[TrendPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Proof response
# ---------------------------------------------------------------------------


class ProofCapstoneArtifact(BaseModel):
    exercise_id: uuid.UUID
    title: str
    draft_count: int = 0
    last_score: int | None = None
    days_since_last_edit: int | None = None


class ProofAIReviewItem(BaseModel):
    id: uuid.UUID
    problem_title: str | None = None
    score: int | None = None
    created_at: datetime


class ProofAIReviews(BaseModel):
    count: int = 0
    last_three: list[ProofAIReviewItem] = Field(default_factory=list)


class ProofMockReport(BaseModel):
    session_id: uuid.UUID
    headline: str | None = None
    verdict: str | None = None
    created_at: datetime
    target_role: str | None = None


class ProofAutopsy(BaseModel):
    id: uuid.UUID
    project_title: str
    headline: str
    overall_score: int
    created_at: datetime


class ProofPeerReviews(BaseModel):
    count_received: int = 0
    count_given: int = 0


class ProofPrimaryArtifact(BaseModel):
    title: str | None = None
    snippet: str | None = None


class ProofResponse(BaseModel):
    capstone_artifacts: list[ProofCapstoneArtifact] = Field(default_factory=list)
    ai_reviews: ProofAIReviews = Field(default_factory=ProofAIReviews)
    mock_reports: list[ProofMockReport] = Field(default_factory=list)
    autopsies: list[ProofAutopsy] = Field(default_factory=list)
    peer_reviews: ProofPeerReviews = Field(default_factory=ProofPeerReviews)
    last_capstone_summary: ProofPrimaryArtifact | None = None
