"""Tests for app/services/welcome_prompt_service (Tutor refactor 2026-04-26).

Pure helpers (`_filter_for_mode`, `_topup`, `_DEFAULT_FALLBACK`) are tested
without a DB. `build_welcome_prompts` is exercised end-to-end against an
in-memory SQLite session populated with a lesson + failed exercise + skill +
misconception so each personalization branch fires.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.skill import Skill
from app.models.student_misconception import StudentMisconception
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.services.welcome_prompt_service import (
    MAX_PROMPTS,
    WelcomePrompt,
    _DEFAULT_FALLBACK,
    _filter_for_mode,
    _topup,
    build_welcome_prompts,
)


# ---------------------------------------------------------------------------
# _filter_for_mode (pure)
# ---------------------------------------------------------------------------


def _sample_prompts() -> list[WelcomePrompt]:
    return [
        WelcomePrompt(text="t1", icon="🎓", kind="tutor", rationale="r"),
        WelcomePrompt(text="c1", icon="🐍", kind="code", rationale="r"),
        WelcomePrompt(text="q1", icon="⚡", kind="quiz", rationale="r"),
        WelcomePrompt(text="ca1", icon="💼", kind="career", rationale="r"),
        WelcomePrompt(text="a1", icon="✨", kind="auto", rationale="r"),
    ]


def test_filter_for_mode_auto_returns_all() -> None:
    prompts = _sample_prompts()
    out = _filter_for_mode(prompts, "auto")
    assert out == prompts


def test_filter_for_mode_tutor_keeps_tutor_and_auto() -> None:
    out = _filter_for_mode(_sample_prompts(), "tutor")
    kinds = {p.kind for p in out}
    assert kinds == {"tutor", "auto"}


def test_filter_for_mode_code_keeps_code_and_auto() -> None:
    out = _filter_for_mode(_sample_prompts(), "code")
    kinds = {p.kind for p in out}
    assert kinds == {"code", "auto"}


def test_filter_for_mode_quiz_keeps_quiz_and_auto() -> None:
    out = _filter_for_mode(_sample_prompts(), "quiz")
    kinds = {p.kind for p in out}
    assert kinds == {"quiz", "auto"}


def test_filter_for_mode_career_keeps_career_and_auto() -> None:
    out = _filter_for_mode(_sample_prompts(), "career")
    kinds = {p.kind for p in out}
    assert kinds == {"career", "auto"}


def test_filter_for_mode_returns_empty_when_no_match() -> None:
    only_quiz = [
        WelcomePrompt(text="q", icon="⚡", kind="quiz", rationale="r"),
    ]
    assert _filter_for_mode(only_quiz, "code") == []


# ---------------------------------------------------------------------------
# _topup (pure)
# ---------------------------------------------------------------------------


def test_topup_pads_up_to_target() -> None:
    chosen = [
        WelcomePrompt(text="own", icon="🧠", kind="tutor", rationale="r"),
    ]
    out = _topup(chosen, list(_DEFAULT_FALLBACK), target=4)
    assert len(out) == 4
    assert out[0].text == "own"


def test_topup_dedupes_by_lowercase_text() -> None:
    chosen = [
        WelcomePrompt(
            text="WHAT IS RAG AND HOW DOES IT WORK?",
            icon="🔍",
            kind="tutor",
            rationale="r",
        ),
    ]
    out = _topup(chosen, list(_DEFAULT_FALLBACK), target=10)
    texts_lower = [p.text.lower() for p in out]
    # Default fallback contains "What is RAG and how does it work?" in any
    # casing — must not appear twice.
    assert len(texts_lower) == len(set(texts_lower))


def test_topup_does_not_exceed_target() -> None:
    chosen: list[WelcomePrompt] = []
    out = _topup(chosen, list(_DEFAULT_FALLBACK), target=3)
    assert len(out) == 3


def test_topup_does_not_shrink_chosen_when_already_above_target() -> None:
    chosen = list(_DEFAULT_FALLBACK)  # 6 items
    out = _topup(chosen, [], target=2)
    # Should not strip anything — only padding behavior is defined.
    assert len(out) == len(_DEFAULT_FALLBACK)


def test_default_fallback_has_six_entries() -> None:
    assert len(_DEFAULT_FALLBACK) == MAX_PROMPTS


# ---------------------------------------------------------------------------
# build_welcome_prompts — DB integration
# ---------------------------------------------------------------------------


async def _seed_signal_world(
    db: AsyncSession, *, email: str = "wp@test.dev"
) -> User:
    """Build a user with progress + failed exercise + skill + misconception."""
    user = User(email=email, full_name="Welcome User", role="student")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    course = Course(
        title="C", slug=f"c-{email}", description="d", difficulty="beginner"
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    lesson = Lesson(
        course_id=course.id,
        title="Vector Search Basics",
        slug=f"vsb-{email}",
        order=1,
        duration_seconds=60,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)

    db.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson.id,
            status="in_progress",
        )
    )

    exercise = Exercise(
        lesson_id=lesson.id,
        title="Build a Retriever",
        description="ship it",
        difficulty="medium",
        pass_score=70,
    )
    db.add(exercise)
    await db.commit()
    await db.refresh(exercise)

    db.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=exercise.id,
            status="graded",
            score=42,  # below pass_score
            code="x = 1",
        )
    )

    skill = Skill(
        slug=f"async-{email}",
        name="Async Python",
        description="d",
        difficulty=2,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)

    db.add(
        UserSkillState(
            user_id=user.id,
            skill_id=skill.id,
            mastery_level="practicing",
            confidence=0.5,
            last_touched_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )

    db.add(
        StudentMisconception(
            user_id=user.id,
            topic="cosine similarity",
            student_assertion="cosine returns degrees",
            tutor_correction="cosine returns -1..1",
        )
    )
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_build_welcome_prompts_includes_personalized_signals(
    db_session: AsyncSession,
) -> None:
    user = await _seed_signal_world(db_session)
    prompts = await build_welcome_prompts(db_session, user=user, mode="auto")
    assert prompts, "expected at least one prompt"
    assert len(prompts) <= MAX_PROMPTS

    rationales = {p.rationale for p in prompts}
    # Personalized branches should fire for the seeded signals.
    assert "last_lesson" in rationales
    assert "failed_exercise" in rationales
    assert "last_skill" in rationales
    assert "misconception" in rationales


@pytest.mark.asyncio
async def test_build_welcome_prompts_blank_user_returns_fallback(
    db_session: AsyncSession,
) -> None:
    user = User(email="empty@test.dev", full_name="Empty", role="student")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    prompts = await build_welcome_prompts(db_session, user=user, mode="auto")
    assert len(prompts) == MAX_PROMPTS
    # All should have rationale=='default' (fallback) plus 'standing_career'
    # which the service always appends.
    rationales = {p.rationale for p in prompts}
    assert rationales.issubset({"default", "standing_career"})


@pytest.mark.asyncio
async def test_build_welcome_prompts_mode_filter_keeps_matching_kinds(
    db_session: AsyncSession,
) -> None:
    user = await _seed_signal_world(db_session, email="wp-tutor@test.dev")
    prompts = await build_welcome_prompts(db_session, user=user, mode="tutor")
    assert prompts
    for p in prompts:
        assert p.kind in {"tutor", "auto"}


@pytest.mark.asyncio
async def test_build_welcome_prompts_caps_at_max_prompts(
    db_session: AsyncSession,
) -> None:
    user = await _seed_signal_world(db_session, email="wp-cap@test.dev")
    prompts = await build_welcome_prompts(db_session, user=user, mode="auto")
    assert len(prompts) <= MAX_PROMPTS
