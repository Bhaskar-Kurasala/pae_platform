"""Pydantic schemas for career endpoints (#168 #169 #171 #172 #173)."""

import uuid

from pydantic import BaseModel


class ResumeResponse(BaseModel):
    id: uuid.UUID
    title: str
    summary: str | None
    skills_snapshot: list | None
    linkedin_blurb: str | None


class FitScoreRequest(BaseModel):
    jd_text: str
    jd_title: str = "Software Engineer"


class FitScoreResponse(BaseModel):
    fit_score: float
    matched_skills: list[str]
    skill_gap: list[str]


class LearningPlanResponse(BaseModel):
    plan: str
    skill_gap: list[str]


class InterviewQuestionItem(BaseModel):
    id: uuid.UUID
    question: str
    answer_hint: str | None
    difficulty: str
    category: str
    skill_tags: list | None
