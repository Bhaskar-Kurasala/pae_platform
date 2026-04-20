"""Pydantic schemas for career endpoints (#168 #169 #171 #172 #173)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ResumeBullet(BaseModel):
    """A single evidence-grounded bullet point for the resume."""

    text: str
    evidence_id: str  # skill name from skill_map that grounds this bullet
    ats_keywords: list[str]


class ResumeResponse(BaseModel):
    """Full structured resume response returned to the client."""

    id: uuid.UUID
    title: str
    summary: str | None
    bullets: list[ResumeBullet]
    skills_snapshot: list | None
    linkedin_blurb: str | None
    ats_keywords: list[str]
    verdict: str | None  # strong_fit | good_fit | needs_work


class ResumeRegenerateRequest(BaseModel):
    """Request body for the resume regeneration endpoint."""

    force: bool = False  # when True, clears cache and regenerates even if summary exists


class FitScoreRequest(BaseModel):
    jd_text: str
    jd_title: str = "Software Engineer"


class SkillBucket(BaseModel):
    proven: list[str]    # mastered ≥70%
    unproven: list[str]  # present but <70%
    missing: list[str]   # not in profile at all


class FitVerdict(BaseModel):
    verdict: str           # apply | skill_up | skip
    verdict_reason: str
    fit_score: float
    buckets: SkillBucket
    weeks_to_close: int
    top_3_actions: list[str]


class FitScoreResponse(BaseModel):
    fit_score: float
    matched_skills: list[str]
    skill_gap: list[str]
    verdict: FitVerdict | None = None


class LearningPlanResponse(BaseModel):
    plan: str
    skill_gap: list[str]
    verdict: FitVerdict | None = None


class InterviewQuestionItem(BaseModel):
    id: uuid.UUID
    question: str
    answer_hint: str | None
    difficulty: str
    category: str
    skill_tags: list | None


class SaveJdRequest(BaseModel):
    title: str
    company: str | None = None
    jd_text: str


class JdLibraryItem(BaseModel):
    id: uuid.UUID
    title: str
    company: str | None
    last_fit_score: float | None
    verdict: str | None
    created_at: datetime
