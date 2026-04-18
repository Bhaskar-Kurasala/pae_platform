"""Career service — resume building, interview prep, JD fit analysis.

Covers tickets:
  #168 Resume builder (+ #174 LinkedIn blurb)
  #169 Interview question bank (searchable)
  #171 JD fit score
  #172 Skill gap vs JD
  #173 Learning plan from JD
"""

from __future__ import annotations

import uuid

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import TextBlock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.interview_question import InterviewQuestion
from app.models.resume import Resume
from app.models.skill import Skill
from app.models.user_skill_state import UserSkillState

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Pure helpers (no DB, no LLM — fully unit-testable)
# ---------------------------------------------------------------------------


def compute_fit_score(
    student_skills: dict[str, float],
    jd_skills: list[str],
) -> float:
    """Return 0-1 fit score: average confidence of JD skills the student has."""
    if not jd_skills:
        return 0.0
    total = sum(student_skills.get(skill.lower(), 0.0) for skill in jd_skills)
    return round(total / len(jd_skills), 2)


def compute_skill_gap(
    student_skills: dict[str, float],
    jd_skills: list[str],
    mastery_threshold: float = 0.7,
) -> list[str]:
    """Return JD skills the student doesn't have or hasn't mastered."""
    return [
        skill for skill in jd_skills if student_skills.get(skill.lower(), 0.0) < mastery_threshold
    ]


def extract_jd_skills(jd_text: str) -> list[str]:
    """Extract likely technical skill keywords from a job description.

    Simple keyword extraction — no LLM to keep this fast and cheap.
    """
    tech_keywords = [
        "python",
        "javascript",
        "typescript",
        "fastapi",
        "django",
        "react",
        "docker",
        "kubernetes",
        "llm",
        "langchain",
        "openai",
        "anthropic",
        "sql",
        "postgresql",
        "redis",
        "celery",
        "machine learning",
        "nlp",
        "rag",
        "embeddings",
        "vector",
        "api",
        "rest",
        "graphql",
    ]
    lower = jd_text.lower()
    return [kw for kw in tech_keywords if kw in lower]


# ---------------------------------------------------------------------------
# Async DB functions
# ---------------------------------------------------------------------------


async def get_student_skill_map(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> dict[str, float]:
    """Return {skill_name_lower: confidence} for the student."""
    result = await db.execute(
        select(Skill.name, UserSkillState.confidence)
        .join(UserSkillState, UserSkillState.skill_id == Skill.id)
        .where(UserSkillState.user_id == user_id)
    )
    return {name.lower(): float(confidence or 0.0) for name, confidence in result.all()}


async def get_or_create_resume(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> Resume:
    """Fetch or create a resume row for the user."""
    result = await db.execute(select(Resume).where(Resume.user_id == user_id).limit(1))
    resume = result.scalar_one_or_none()
    if resume is None:
        resume = Resume(user_id=user_id)
        db.add(resume)
        await db.commit()
        await db.refresh(resume)
        log.info("career.resume_created", user_id=str(user_id))
    return resume


async def generate_resume_summary(
    *,
    skill_map: dict[str, float],
) -> str:
    """Use Claude to generate a professional resume summary."""
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    top_skills = sorted(skill_map.items(), key=lambda x: x[1], reverse=True)[:8]
    skills_str = ", ".join(f"{k} ({round(v * 100)}%)" for k, v in top_skills)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a 2-3 sentence professional resume summary for an AI engineer "
                    f"with these skills: {skills_str}. "
                    f"Be specific, concrete, and avoid generic phrases."
                ),
            }
        ],
    )
    first = response.content[0] if response.content else None
    summary: str = first.text if isinstance(first, TextBlock) else ""
    log.info("career.resume_summary_generated", skill_count=len(top_skills))
    return summary


async def generate_learning_plan(
    *,
    skill_gap: list[str],
    jd_title: str,
) -> str:
    """Use Claude to generate a targeted learning plan for a JD."""
    if not skill_gap:
        return "Your skill profile is a strong match for this role. Focus on interview preparation."

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    gap_str = ", ".join(skill_gap[:6])

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Create a 4-week learning plan to close this skill gap for a {jd_title} role. "
                    f"Skills to learn: {gap_str}. "
                    f"Format as: Week 1: ..., Week 2: ..., Week 3: ..., Week 4: ... "
                    f"Be specific about what to build or study each week."
                ),
            }
        ],
    )
    first = response.content[0] if response.content else None
    plan: str = first.text if isinstance(first, TextBlock) else ""
    log.info("career.learning_plan_generated", gap_count=len(skill_gap))
    return plan


async def search_interview_questions(
    db: AsyncSession,
    *,
    query: str,
    limit: int = 20,
) -> list[InterviewQuestion]:
    """Simple substring search on interview questions.

    Searches question text.  skill_tags is JSON so we filter in Python to
    stay compatible with both SQLite (tests) and PostgreSQL (production).
    """
    stmt = select(InterviewQuestion)
    if query:
        stmt = stmt.where(InterviewQuestion.question.ilike(f"%{query}%"))
    stmt = stmt.limit(limit * 2)  # fetch extra so we can filter tags in Python
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    if query:
        q_lower = query.lower()
        # Also include rows where skill_tags contains the query string
        tag_matches = [
            r for r in rows if r.skill_tags and any(q_lower in str(t).lower() for t in r.skill_tags)
        ]
        # Merge without duplicates, preserving question-match order
        seen = {r.id for r in rows}
        for r in tag_matches:
            if r.id not in seen:
                rows.append(r)
                seen.add(r.id)

    return rows[:limit]
