"""Career service — resume building, interview prep, JD fit analysis.

Covers tickets:
  #168 Resume builder (+ #174 LinkedIn blurb)
  #169 Interview question bank (searchable)
  #171 JD fit score (+ three-bucket gap analysis + verdict)
  #172 Skill gap vs JD
  #173 Learning plan from JD
  #175 JD library (save / list / delete)
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, TypedDict

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_factory import build_llm
from app.core.config import settings
from app.models.interview_question import InterviewQuestion
from app.models.jd_library import JdLibrary
from app.models.resume import Resume
from app.models.skill import Skill
from app.models.user_skill_state import UserSkillState
from app.schemas.career import FitVerdict, SkillBucket

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# TypedDict for structured resume content returned by Claude
# ---------------------------------------------------------------------------


class BulletDict(TypedDict):
    text: str
    evidence_id: str
    ats_keywords: list[str]


class ResumeContent(TypedDict):
    summary: str
    bullets: list[BulletDict]
    linkedin_blurb: str
    ats_keywords: list[str]


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


def compute_three_bucket_gap(
    student_skills: dict[str, float],
    jd_skills: list[str],
    mastery_threshold: float = 0.7,
) -> tuple[list[str], list[str], list[str]]:
    """Return (proven, unproven, missing) skill buckets.

    proven  — skill is in profile with confidence ≥ mastery_threshold
    unproven — skill is in profile but confidence < mastery_threshold
    missing  — skill is absent from the student's profile entirely
    """
    proven: list[str] = []
    unproven: list[str] = []
    missing: list[str] = []
    for skill in jd_skills:
        conf = student_skills.get(skill.lower(), -1.0)
        if conf < 0:
            missing.append(skill)
        elif conf >= mastery_threshold:
            proven.append(skill)
        else:
            unproven.append(skill)
    return proven, unproven, missing


def compute_verdict(
    fit_score: float,
    proven: list[str],
    unproven: list[str],
    missing: list[str],
) -> FitVerdict:
    """Derive an apply / skill_up / skip verdict from the bucket analysis."""
    weeks: int = len(missing) * 2 + len(unproven) * 1

    if fit_score >= 0.7:
        verdict = "apply"
        gap_preview = ", ".join(unproven[:2]) if unproven else "remaining gaps"
        reason = (
            f"Strong match ({round(fit_score * 100)}%). "
            f"Focus on demonstrating {gap_preview} before applying."
        )
    elif fit_score >= 0.4:
        verdict = "skill_up"
        reason = (
            f"Moderate match ({round(fit_score * 100)}%). "
            f"Close {len(missing)} gap(s) in ~{weeks} week(s) first."
        )
    else:
        verdict = "skip"
        reason = (
            f"Significant gap ({round(fit_score * 100)}%). "
            f"Consider this role after completing more coursework."
        )

    top_actions: list[str] = []
    if missing:
        top_actions.append(f"Learn: {', '.join(missing[:3])}")
    if unproven:
        top_actions.append(f"Build evidence for: {', '.join(unproven[:2])}")
    top_actions.append("Practice interview questions for matched skills")

    return FitVerdict(
        verdict=verdict,
        verdict_reason=reason,
        fit_score=fit_score,
        buckets=SkillBucket(proven=proven, unproven=unproven, missing=missing),
        weeks_to_close=weeks,
        top_3_actions=top_actions[:3],
    )


def derive_resume_verdict(skill_map: dict[str, float]) -> str:
    """Derive strong_fit | good_fit | needs_work from average skill confidence."""
    if not skill_map:
        return "needs_work"
    avg = sum(skill_map.values()) / len(skill_map)
    if avg >= 0.75:
        return "strong_fit"
    if avg >= 0.5:
        return "good_fit"
    return "needs_work"


def normalize_llm_content(content: Any) -> str:
    """Coerce a LangChain ``response.content`` into a plain string.

    MiniMax (Anthropic-compatible endpoint) returns ``content`` as a list of
    dicts mixing ``thinking`` and ``text`` blocks; Anthropic Claude returns
    plain ``str``. Concatenate every ``text`` block in order and skip any
    block whose ``type`` is ``thinking``. Falls back to ``str(content)`` for
    unknown shapes.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "thinking":
                    continue
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first balanced {…} JSON object from *text*.

    The LLM response may include thinking text or markdown fences before the
    JSON payload, so we scan for the first { and walk the string tracking
    brace depth until we find the matching }.
    """
    match = re.search(r"\{", text)
    if not match:
        return {}
    start = match.start()
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])  # noqa: E203
                except json.JSONDecodeError:
                    return {}
    return {}


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


async def get_exercise_count(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> int:
    """Count completed exercise submissions for *user_id*.

    Returns 0 gracefully if the model cannot be imported or any DB error occurs.
    """
    try:
        from app.models.exercise_submission import (  # local import avoids circular deps
            ExerciseSubmission,
        )

        result = await db.execute(
            select(func.count())
            .select_from(ExerciseSubmission)
            .where(
                ExerciseSubmission.student_id == user_id,
                ExerciseSubmission.status == "completed",
            )
        )
        count: int = result.scalar_one_or_none() or 0
        return count
    except Exception:
        log.warning("career.exercise_count_unavailable", user_id=str(user_id))
        return 0


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


async def generate_resume_content(
    *,
    skill_map: dict[str, float],
    exercise_count: int = 0,
) -> ResumeContent:
    """Use Claude to generate structured, evidence-grounded resume content.

    The prompt injects the full skill_map JSON so Claude can reference actual
    proficiency data.  Output is parsed from the first {…} block in the
    response.  Falls back to empty lists on JSON parse failure — never raises.
    """
    llm = build_llm(max_tokens=1000)

    skill_map_json = json.dumps(skill_map, indent=2)
    top_skills = sorted(skill_map.items(), key=lambda x: x[1], reverse=True)[:10]
    top_skills_str = ", ".join(f"{k} ({round(v * 100)}%)" for k, v in top_skills)

    system_prompt = (
        "You are an expert technical resume writer specialising in AI and software engineering roles. "
        "You write concise, ATS-optimised content grounded in real evidence from the student's skill profile. "
        "Never invent skills or experiences not present in the skill map. "
        "Always respond with a single JSON object — no markdown fences, no preamble, no trailing text."
    )

    user_prompt = (
        "Generate resume content for an AI/software engineering student.\n\n"
        f"SKILL MAP (skill -> confidence 0-1):\n{skill_map_json}\n\n"
        "ADDITIONAL CONTEXT:\n"
        f"- Completed exercises: {exercise_count}\n"
        f"- Top skills by confidence: {top_skills_str}\n\n"
        'Return ONLY a JSON object with this exact schema:\n'
        '{\n'
        '  "summary": "<2-3 sentence professional resume summary, concrete and specific>",\n'
        '  "bullets": [\n'
        '    {\n'
        '      "text": "<achievement bullet in past-tense action-verb format, quantified where possible>",\n'
        '      "evidence_id": "<skill name from the skill map that grounds this bullet>",\n'
        '      "ats_keywords": ["<keyword1>", "<keyword2>"]\n'
        '    }\n'
        '  ],\n'
        '  "linkedin_blurb": "<3-4 sentence LinkedIn About section>",\n'
        '  "ats_keywords": ["<global keyword list for this resume, 8-12 items>"]\n'
        '}\n\n'
        "Rules:\n"
        "- Write 4-6 bullets, each tied to a distinct skill in the map.\n"
        "- Only reference skills present in the skill_map JSON above.\n"
        "- ats_keywords at the bullet level should be 2-4 terms each.\n"
        "- Global ats_keywords should cover the top 8-12 technical terms across all bullets.\n"
        "- Do NOT wrap the JSON in markdown code fences."
    )

    result = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    raw_text = result.content if isinstance(result.content, str) else ""

    parsed = extract_json_object(raw_text)

    summary: str = parsed.get("summary") or ""
    linkedin_blurb: str = parsed.get("linkedin_blurb") or ""
    ats_keywords: list[str] = parsed.get("ats_keywords") or []

    raw_bullets = parsed.get("bullets") or []
    bullets: list[BulletDict] = []
    for b in raw_bullets:
        if isinstance(b, dict) and b.get("text") and b.get("evidence_id"):
            bullets.append(
                BulletDict(
                    text=str(b["text"]),
                    evidence_id=str(b["evidence_id"]),
                    ats_keywords=[str(k) for k in (b.get("ats_keywords") or [])],
                )
            )

    log.info(
        "career.resume_content_generated",
        bullet_count=len(bullets),
        ats_keyword_count=len(ats_keywords),
        skill_count=len(skill_map),
        exercise_count=exercise_count,
    )
    return ResumeContent(
        summary=summary,
        bullets=bullets,
        linkedin_blurb=linkedin_blurb,
        ats_keywords=ats_keywords,
    )


async def generate_resume_summary(
    *,
    skill_map: dict[str, float],
) -> str:
    """Backward-compatible wrapper — delegates to generate_resume_content.

    Returns only the summary string so old call sites continue to work.
    """
    content = await generate_resume_content(skill_map=skill_map)
    return content["summary"]


async def generate_learning_plan(
    *,
    skill_gap: list[str],
    jd_title: str,
) -> str:
    """Use Claude to generate a targeted learning plan for a JD."""
    if not skill_gap:
        return "Your skill profile is a strong match for this role. Focus on interview preparation."

    llm = build_llm(max_tokens=500)
    gap_str = ", ".join(skill_gap[:6])

    result = await llm.ainvoke([
        HumanMessage(content=(
            f"Create a 4-week learning plan to close this skill gap for a {jd_title} role. "
            f"Skills to learn: {gap_str}. "
            f"Format as: Week 1: ..., Week 2: ..., Week 3: ..., Week 4: ... "
            f"Be specific about what to build or study each week."
        ))
    ])
    plan: str = result.content if isinstance(result.content, str) else ""
    log.info("career.learning_plan_generated", gap_count=len(skill_gap))
    return plan


# ---------------------------------------------------------------------------
# Resume cache management
# ---------------------------------------------------------------------------


async def _persist_resume_content(
    db: AsyncSession,
    resume: Resume,
    content: ResumeContent,
    skill_map: dict[str, float],
) -> None:
    """Write LLM-generated content back to *resume* and commit."""
    resume.summary = content["summary"]
    resume.bullets = list(content["bullets"])  # JSON-serialisable list of dicts
    resume.linkedin_blurb = content["linkedin_blurb"]
    resume.ats_keywords = content["ats_keywords"]
    resume.skills_snapshot = [
        {"skill": k, "confidence": v}
        for k, v in sorted(skill_map.items(), key=lambda x: x[1], reverse=True)
    ]
    resume.verdict = derive_resume_verdict(skill_map)
    await db.commit()
    await db.refresh(resume)


async def regenerate_resume(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    force: bool = False,
) -> Resume:
    """Clear cached resume content and regenerate via Claude.

    When *force* is False, only regenerates if the summary is missing.
    """
    resume = await get_or_create_resume(db, user_id=user_id)

    if resume.summary and not force:
        log.info("career.resume_cache_hit", user_id=str(user_id))
        return resume

    # Clear stale content before regenerating
    resume.summary = None
    resume.bullets = None
    resume.linkedin_blurb = None
    resume.ats_keywords = None
    resume.verdict = None

    skill_map = await get_student_skill_map(db, user_id=user_id)
    exercise_count = await get_exercise_count(db, user_id=user_id)
    content = await generate_resume_content(skill_map=skill_map, exercise_count=exercise_count)
    await _persist_resume_content(db, resume, content, skill_map)

    log.info("career.resume_regenerated", user_id=str(user_id), force=force)
    return resume


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


# ---------------------------------------------------------------------------
# JD Library DB functions
# ---------------------------------------------------------------------------


async def save_jd_to_library(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    company: str | None,
    jd_text: str,
    fit_score: float | None,
    verdict: str | None,
) -> JdLibrary:
    """Persist a job description to the user's JD library.

    If a row with the same user_id + title already exists it is updated
    in-place rather than creating a duplicate.
    """
    result = await db.execute(
        select(JdLibrary).where(
            JdLibrary.user_id == user_id,
            JdLibrary.title == title,
        )
    )
    item = result.scalar_one_or_none()

    if item is None:
        item = JdLibrary(
            user_id=user_id,
            title=title,
            company=company,
            jd_text=jd_text,
            last_fit_score=fit_score,
            verdict=verdict,
        )
        db.add(item)
        log.info("career.jd_library.saved", user_id=str(user_id), title=title)
    else:
        item.company = company
        item.jd_text = jd_text
        item.last_fit_score = fit_score
        item.verdict = verdict
        log.info("career.jd_library.updated", user_id=str(user_id), title=title)

    await db.commit()
    await db.refresh(item)
    return item


async def get_jd_library(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[JdLibrary]:
    """Return all saved JDs for a user, newest first."""
    result = await db.execute(
        select(JdLibrary)
        .where(JdLibrary.user_id == user_id)
        .order_by(JdLibrary.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_jd_from_library(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    jd_id: uuid.UUID,
) -> bool:
    """Delete a saved JD.  Returns True if a row was deleted, False if not found."""
    result = await db.execute(
        delete(JdLibrary).where(
            JdLibrary.id == jd_id,
            JdLibrary.user_id == user_id,
        )
    )
    await db.commit()
    deleted: bool = result.rowcount > 0  # type: ignore[union-attr]
    if deleted:
        log.info("career.jd_library.deleted", user_id=str(user_id), jd_id=str(jd_id))
    else:
        log.warning(
            "career.jd_library.delete_not_found",
            user_id=str(user_id),
            jd_id=str(jd_id),
        )
    return deleted
