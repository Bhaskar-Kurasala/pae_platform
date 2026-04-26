"""Profile aggregator — assembles the verified BaseResume + intake context
that the tailoring agent is allowed to draw from.

The hallucination guardrail later compares every claim in the generated
resume against the *evidence allowlist* this module returns.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resume import Resume
from app.services.career_service import (
    get_exercise_count,
    get_or_create_resume,
    get_student_skill_map,
    regenerate_resume,
)

log = structlog.get_logger()


# Fixed intake question bank. The selector below removes any question whose
# answer is already known from the platform profile or persisted intake_data.
INTAKE_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "target_role",
        "label": "What role title are you targeting?",
        "kind": "text",
        "required": "true",
    },
    {
        "id": "why_company",
        "label": "Why this company specifically? (1–2 sentences)",
        "kind": "textarea",
        "required": "true",
    },
    {
        "id": "non_platform_experience",
        "label": "Any work experience outside CareerForge we should include?",
        "kind": "textarea",
        "required": "false",
    },
    {
        "id": "education",
        "label": "Education — degree, school, year (one line)",
        "kind": "text",
        "required": "false",
    },
    {
        "id": "salary_expectation",
        "label": "Salary expectation (optional)",
        "kind": "text",
        "required": "false",
    },
    {
        "id": "location_preference",
        "label": "Preferred location / remote?",
        "kind": "text",
        "required": "false",
    },
    {
        "id": "availability",
        "label": "When can you start?",
        "kind": "text",
        "required": "false",
    },
]


@dataclass
class BaseResumeBundle:
    """Everything the tailoring agent is allowed to cite."""

    resume: Resume
    skill_map: dict[str, float]
    exercise_count: int
    intake_data: dict[str, Any]

    # Names allowed as `evidence_id` values in tailored bullets. Anything
    # outside this set is treated as a hallucination by the validator.
    evidence_allowlist: set[str] = field(default_factory=set)

    def evidence_summary(self) -> dict[str, Any]:
        """Compact JSON the LLM sees — never sends raw DB objects."""
        bullets = self.resume.bullets or []
        return {
            "summary": self.resume.summary or "",
            "verdict": self.resume.verdict or "needs_work",
            "bullets": [
                {
                    "text": b.get("text", ""),
                    "evidence_id": b.get("evidence_id", ""),
                    "ats_keywords": b.get("ats_keywords", []),
                }
                for b in bullets
                if isinstance(b, dict)
            ],
            "skills": [
                {"name": k, "confidence": round(v, 2)}
                for k, v in sorted(self.skill_map.items(), key=lambda x: x[1], reverse=True)
            ],
            "exercise_count": self.exercise_count,
            "self_attested": {
                "non_platform_experience": self.intake_data.get(
                    "non_platform_experience", []
                ),
                "education": self.intake_data.get("education", []),
            },
        }


def _build_evidence_allowlist(
    skill_map: dict[str, float],
    intake_data: dict[str, Any],
) -> set[str]:
    """Anything the tailoring agent may reference as an evidence_id.

    Skill names appear lowercased — the validator lowercases evidence_ids
    before comparing.
    """
    allowlist: set[str] = set()
    allowlist.update(skill_map.keys())  # already lowercased

    # Self-attested experience entries must declare an `id` to be citable.
    for entry in intake_data.get("non_platform_experience", []) or []:
        if isinstance(entry, dict) and entry.get("id"):
            allowlist.add(str(entry["id"]).lower())
    for entry in intake_data.get("education", []) or []:
        if isinstance(entry, dict) and entry.get("id"):
            allowlist.add(str(entry["id"]).lower())

    # Always allow the synthetic "exercise_volume" evidence so the agent can
    # cite the platform-tracked number of completed exercises.
    if any(
        True
        for _ in (1,)  # dummy — readability
    ):
        allowlist.add("exercise_volume")

    return allowlist


async def build_base_resume_bundle(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> BaseResumeBundle:
    """Fetch + lazily regenerate the BaseResume and assemble the bundle.

    Mirrors the existing /career/resume flow: if the user has no cached
    resume content, it's generated now from the skill map.
    """
    resume = await regenerate_resume(db, user_id=user_id, force=False)
    if resume.summary is None:
        # If regenerate_resume bailed without producing content (no LLM key
        # in dev), the skill map is still the source of truth — we just
        # ship a thinner allowlist.
        resume = await get_or_create_resume(db, user_id=user_id)

    skill_map = await get_student_skill_map(db, user_id=user_id)
    exercise_count = await get_exercise_count(db, user_id=user_id)
    intake_data = resume.intake_data or {}

    bundle = BaseResumeBundle(
        resume=resume,
        skill_map=skill_map,
        exercise_count=exercise_count,
        intake_data=intake_data,
        evidence_allowlist=_build_evidence_allowlist(skill_map, intake_data),
    )
    log.info(
        "profile_aggregator.bundle_built",
        user_id=str(user_id),
        skill_count=len(skill_map),
        evidence_size=len(bundle.evidence_allowlist),
    )
    return bundle


def select_intake_questions(
    bundle: BaseResumeBundle,
    *,
    answered: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Pick the 4–7 questions to actually ask.

    Skips a question when the answer is already on the user's profile,
    persisted in their intake_data, or supplied in *answered*.
    """
    answered = answered or {}
    skip_ids: set[str] = set(answered.keys())

    intake = bundle.intake_data or {}
    if intake.get("preferences", {}).get("target_role"):
        skip_ids.add("target_role")
    if intake.get("preferences", {}).get("salary_expectation"):
        skip_ids.add("salary_expectation")
    if intake.get("preferences", {}).get("location"):
        skip_ids.add("location_preference")
    if intake.get("preferences", {}).get("availability"):
        skip_ids.add("availability")
    if intake.get("non_platform_experience"):
        skip_ids.add("non_platform_experience")
    if intake.get("education"):
        skip_ids.add("education")

    selected = [q for q in INTAKE_QUESTIONS if q["id"] not in skip_ids]

    # Always ask at least 4, at most 7. The bank holds 7 — required ones come
    # first when we trim.
    if len(selected) > 7:
        selected = selected[:7]
    if len(selected) < 4:
        # Top up from the original list, preserving order, to reach 4.
        for q in INTAKE_QUESTIONS:
            if q not in selected:
                selected.append(q)
            if len(selected) >= 4:
                break
    return selected
