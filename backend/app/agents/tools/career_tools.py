"""Career-side tools.

`search_jobs` and `parse_jd` are the two pillars of the eventual
Career Studio agentic system. Both are stubs; both have stable
schemas the implementation will honour.

`search_jobs` will eventually wrap a job-board API (Adzuna, RemoteOK,
or scraped postings); `parse_jd` will use the same Claude pipeline
as the existing `jd_decoder` service, just exposed through the
registry so the executor's audit row covers it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.tools import tool


# ── search_jobs ─────────────────────────────────────────────────────


class SearchJobsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_keywords: list[str] = Field(min_length=1, max_length=20)
    location: str | None = Field(default=None, max_length=200)
    remote_ok: bool = True
    seniority: Literal["any", "junior", "mid", "senior", "staff"] = "any"
    posted_within_days: int = Field(default=30, ge=1, le=365)
    k: int = Field(default=10, ge=1, le=50)


class JobMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(description="Provider-specific external id")
    title: str
    company: str
    location: str
    remote: bool
    posted_at: datetime
    apply_url: str
    salary_low: int | None = Field(default=None, ge=0)
    salary_high: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=8)
    score: float = Field(ge=0.0, le=1.0)


class SearchJobsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches: list[JobMatch]
    used_provider: str = Field(
        description=(
            "Provider name — e.g. 'adzuna' or 'mock'. Helps debug "
            "recall quality issues and lets the agent decide whether "
            "to surface salary bands (only some providers carry them)."
        ),
    )


@tool(
    name="search_jobs",
    description=(
        "Search active job postings matching role keywords + location. "
        "Returns ranked matches with apply URL and salary band where "
        "available. Used by career_coach / job_match agentic flows."
    ),
    input_schema=SearchJobsInput,
    output_schema=SearchJobsOutput,
    requires=("read:job_board",),
    cost_estimate=0.0,  # provider quotas vary
    timeout_seconds=20.0,
    is_stub=True,
)
async def search_jobs(args: SearchJobsInput) -> SearchJobsOutput:
    raise NotImplementedError(
        "stub: real implementation wraps a job-board provider behind "
        "this signature. Lands in DX after we pick a provider."
    )


# ── parse_jd ────────────────────────────────────────────────────────


class ParseJDInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=10, max_length=50_000)
    source_url: str | None = Field(default=None, max_length=2000)
    user_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional — when set, parse_jd also computes a match "
            "score against the student's current skill profile."
        ),
    )


class JDRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: str = Field(min_length=1, max_length=120)
    importance: Literal["must_have", "nice_to_have"]
    student_match: float | None = Field(default=None, ge=0.0, le=1.0)


class ParsedJD(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    seniority: Literal["junior", "mid", "senior", "staff", "unknown"] = "unknown"
    company: str | None = None
    requirements: list[JDRequirement]
    summary: str = Field(
        min_length=1,
        description=(
            "Three-sentence human summary of what the role wants. "
            "Used by tailored_resume / cover_letter to bias drafts."
        ),
    )


class ParseJDOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jd: ParsedJD
    overall_match: float | None = Field(default=None, ge=0.0, le=1.0)


@tool(
    name="parse_jd",
    description=(
        "Parse a job description into structured fields (title, "
        "seniority, requirements). When `user_id` is supplied, also "
        "computes per-skill + overall match scores against the "
        "student's current skill profile."
    ),
    input_schema=ParseJDInput,
    output_schema=ParseJDOutput,
    requires=("read:public",),
    cost_estimate=0.012,  # one Claude Haiku call
    timeout_seconds=25.0,
    is_stub=True,
)
async def parse_jd(args: ParseJDInput) -> ParseJDOutput:
    raise NotImplementedError(
        "stub: real implementation reuses the jd_decoder service "
        "Claude pipeline behind this signature. Lands in DX."
    )
