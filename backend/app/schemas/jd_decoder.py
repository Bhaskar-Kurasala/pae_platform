"""Pydantic schemas for the JD Decoder API.

The decoder produces a single response combining (a) the universal JD
analysis and (b) the per-student match score, so a paste-and-run flow is
one round trip.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.readiness import EvidenceChip, NextAction

CultureSeverity = Literal["info", "watch", "warn"]


class FillerFlag(BaseModel):
    """A piece of template language with the decoder's read on it.

    ``phrase`` is the lifted phrase; ``meaning`` is the decoder's plain
    explanation. Phrases are quoted minimally — the system prompt caps
    quoting at ~10 words.
    """

    phrase: str = Field(..., max_length=120)
    meaning: str = Field(..., max_length=240)


class CultureSignal(BaseModel):
    """A culture pattern the decoder noticed.

    Severity tiers:
      * info  — neutral observation
      * watch — pattern often correlates with friction; not damning
      * warn  — pattern often correlates with poor outcomes (burnout
                language, pay opacity + boilerplate growth claims, etc.)
    """

    pattern: str = Field(..., max_length=120)
    severity: CultureSeverity
    note: str = Field(..., max_length=300)


class JdAnalysisPayload(BaseModel):
    role: str
    company: str | None = None
    seniority_read: str
    must_haves: list[str] = Field(default_factory=list, max_length=12)
    wishlist: list[str] = Field(default_factory=list, max_length=12)
    filler_flags: list[FillerFlag] = Field(default_factory=list, max_length=10)
    culture_signals: list[CultureSignal] = Field(
        default_factory=list, max_length=8
    )
    wishlist_inflated: bool = False


class MatchScorePayload(BaseModel):
    """0–100, or null when snapshot too thin to ground a faithful score."""

    score: int | None = Field(default=None, ge=0, le=100)
    headline: str = Field(..., max_length=280)
    evidence: list[EvidenceChip] = Field(default_factory=list, max_length=6)
    next_action: NextAction


class DecodeJdRequest(BaseModel):
    jd_text: str = Field(..., min_length=20, max_length=20_000)


class DecodeJdResponse(BaseModel):
    jd_analysis_id: uuid.UUID
    cached: bool
    analysis: JdAnalysisPayload
    match_score: MatchScorePayload
