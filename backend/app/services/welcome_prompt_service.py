"""Personalized welcome prompts for the Tutor (chat) screen.

Replaces the static SUGGESTED_PROMPTS array on the chat WelcomeScreen with
a per-user, per-mode payload. Strategy is deliberately heuristic — we don't
need an LLM round-trip on every chat-page load; we just want prompts that
respect the student's recent activity + selected mode.

Sources we read (all cheap, indexed):
  - Most recent `student_progress` (resume / continue lesson)
  - Most recent failed exercise submission (debug nudge)
  - Last touched skill via `UserSkillState.last_touched_at` (deepen)
  - Most recent `student_misconception` (revisit a known mistake)

Each prompt has a `kind` so the frontend can route the click to the
correct chat mode (tutor / code / quiz / career / auto).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.skill import Skill
from app.models.student_misconception import StudentMisconception
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.models.user_skill_state import UserSkillState

PromptKind = Literal["tutor", "code", "quiz", "career", "auto"]
ChatMode = Literal["auto", "tutor", "code", "career", "quiz"]

MAX_PROMPTS = 6


@dataclass(frozen=True)
class WelcomePrompt:
    text: str
    icon: str
    kind: PromptKind
    rationale: str  # short tag explaining why we picked this — for analytics


# Curated last-resort fallbacks. Static; only surface when the user has no
# signal at all (brand new account, no enrollments, no progress).
_DEFAULT_FALLBACK: tuple[WelcomePrompt, ...] = (
    WelcomePrompt(
        text="What is RAG and how does it work?",
        icon="🔍",
        kind="tutor",
        rationale="default",
    ),
    WelcomePrompt(
        text="Review my Python code for production readiness",
        icon="🐍",
        kind="code",
        rationale="default",
    ),
    WelcomePrompt(
        text="Quiz me on async/await fundamentals",
        icon="⚡",
        kind="quiz",
        rationale="default",
    ),
    WelcomePrompt(
        text="Help me build my AI engineering portfolio",
        icon="🚀",
        kind="career",
        rationale="default",
    ),
    WelcomePrompt(
        text="Explain the difference between ReAct and Chain-of-Thought",
        icon="🧠",
        kind="tutor",
        rationale="default",
    ),
    WelcomePrompt(
        text="How do I deploy a LangGraph agent to production?",
        icon="☁️",
        kind="auto",
        rationale="default",
    ),
)

_MODE_ICONS: dict[ChatMode, str] = {
    "tutor": "🎓",
    "code": "🐍",
    "quiz": "⚡",
    "career": "💼",
    "auto": "✨",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _filter_for_mode(
    prompts: Iterable[WelcomePrompt], mode: ChatMode
) -> list[WelcomePrompt]:
    """Keep only prompts that match the active mode.

    Auto mode shows everything (mixed kinds is fine in autorouter context).
    For specific modes, we only include prompts whose `kind` matches OR
    whose kind is `auto` (universally useful).
    """
    if mode == "auto":
        return list(prompts)
    return [p for p in prompts if p.kind == mode or p.kind == "auto"]


def _topup(
    chosen: list[WelcomePrompt],
    fallback: Iterable[WelcomePrompt],
    target: int,
) -> list[WelcomePrompt]:
    """Pad `chosen` with fallback prompts up to `target`, dedupe by text."""
    seen = {p.text.lower() for p in chosen}
    for fb in fallback:
        if len(chosen) >= target:
            break
        if fb.text.lower() in seen:
            continue
        chosen.append(fb)
        seen.add(fb.text.lower())
    return chosen


async def _last_lesson(
    db: AsyncSession, *, user_id: uuid.UUID
) -> Lesson | None:
    q = (
        select(Lesson)
        .join(StudentProgress, StudentProgress.lesson_id == Lesson.id)
        .where(StudentProgress.student_id == user_id)
        .order_by(desc(StudentProgress.updated_at))
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def _last_failed_exercise(
    db: AsyncSession, *, user_id: uuid.UUID
) -> Exercise | None:
    q = (
        select(Exercise)
        .join(ExerciseSubmission, ExerciseSubmission.exercise_id == Exercise.id)
        .where(
            ExerciseSubmission.student_id == user_id,
            ExerciseSubmission.status.in_({"failed", "graded"}),
            ExerciseSubmission.score.isnot(None),
            ExerciseSubmission.score < Exercise.pass_score,
        )
        .order_by(desc(ExerciseSubmission.created_at))
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def _last_touched_skill(
    db: AsyncSession, *, user_id: uuid.UUID
) -> Skill | None:
    q = (
        select(Skill)
        .join(UserSkillState, UserSkillState.skill_id == Skill.id)
        .where(
            UserSkillState.user_id == user_id,
            UserSkillState.last_touched_at.is_not(None),
        )
        .order_by(desc(UserSkillState.last_touched_at))
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def _recent_misconception(
    db: AsyncSession, *, user_id: uuid.UUID
) -> StudentMisconception | None:
    cutoff = _now() - timedelta(days=14)
    q = (
        select(StudentMisconception)
        .where(
            StudentMisconception.user_id == user_id,
            StudentMisconception.created_at >= cutoff,
        )
        .order_by(desc(StudentMisconception.created_at))
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def build_welcome_prompts(
    db: AsyncSession,
    *,
    user: User,
    mode: ChatMode = "auto",
) -> list[WelcomePrompt]:
    """Assemble up to MAX_PROMPTS prompts ranked by signal strength."""
    prompts: list[WelcomePrompt] = []

    last_lesson = await _last_lesson(db, user_id=user.id)
    if last_lesson is not None:
        prompts.append(
            WelcomePrompt(
                text=f"Walk me through the key idea of “{last_lesson.title}”",
                icon="📘",
                kind="tutor",
                rationale="last_lesson",
            )
        )
        prompts.append(
            WelcomePrompt(
                text=f"Quiz me on “{last_lesson.title}”",
                icon="⚡",
                kind="quiz",
                rationale="last_lesson",
            )
        )

    failed_ex = await _last_failed_exercise(db, user_id=user.id)
    if failed_ex is not None:
        prompts.append(
            WelcomePrompt(
                text=f"Help me debug “{failed_ex.title}”",
                icon="🐛",
                kind="code",
                rationale="failed_exercise",
            )
        )

    skill = await _last_touched_skill(db, user_id=user.id)
    if skill is not None:
        prompts.append(
            WelcomePrompt(
                text=f"Deepen my understanding of {skill.name}",
                icon="🧠",
                kind="tutor",
                rationale="last_skill",
            )
        )

    misc = await _recent_misconception(db, user_id=user.id)
    if misc is not None and (misc.topic or "").strip():
        prompts.append(
            WelcomePrompt(
                text=f"Revisit my misunderstanding around {misc.topic}",
                icon="🪞",
                kind="tutor",
                rationale="misconception",
            )
        )

    # Add a career nudge if the user hasn't seen one yet — career prompts
    # always survive mode filtering when mode='career' is selected.
    prompts.append(
        WelcomePrompt(
            text="Tighten my resume for an AI engineering role",
            icon="💼",
            kind="career",
            rationale="standing_career",
        )
    )

    filtered = _filter_for_mode(prompts, mode)
    fallback = _filter_for_mode(_DEFAULT_FALLBACK, mode)
    final = _topup(filtered, fallback, target=MAX_PROMPTS)
    return final[:MAX_PROMPTS]


__all__ = [
    "WelcomePrompt",
    "PromptKind",
    "ChatMode",
    "MAX_PROMPTS",
    "build_welcome_prompts",
    "_filter_for_mode",
    "_topup",
    "_DEFAULT_FALLBACK",
    "_MODE_ICONS",
]
