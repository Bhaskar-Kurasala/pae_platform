"""Unit tests for student_context_service (P3 3A-1).

Covers the pure render + bucketing helpers. DB-level loading is exercised
indirectly when 3A-2..3A-8 integration tests run against the stream endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.models.user_skill_state import UserSkillState
from app.services.conversation_memory_service import MemoryEntry
from app.services.student_context_service import (
    SkillDistribution,
    StudentContext,
    _bucket_skills,
    _reflection_age_days,
    render_context_block,
)


# ── render_context_block ─────────────────────────────────────────────────────


def _empty_ctx() -> StudentContext:
    return StudentContext(
        goal_summary=None,
        motivation=None,
        skill_distribution=SkillDistribution(),
        recent_reflection_mood=None,
        recent_reflection_days_ago=None,
        socratic_level=0,
        tutor_mode="standard",
        missing_fields=["goal", "skills", "reflections", "preferences"],
    )


def test_render_empty_context_still_useful() -> None:
    # A brand-new student with no state should still get a non-empty block,
    # so downstream prompt rules can rely on the section always existing.
    block = render_context_block(_empty_ctx())
    assert "Student state" in block
    assert "none set yet" in block
    assert "new learner" in block
    assert "none recorded" in block
    # Should remain short — 6-8 informative lines.
    assert 6 <= len(block.splitlines()) <= 9


def test_render_engaged_student() -> None:
    ctx = StudentContext(
        goal_summary="Land an AI engineering role (~6mo)",
        motivation="career_change",
        skill_distribution=SkillDistribution(
            novice=3, developing=5, proficient=2, mastered=1
        ),
        recent_reflection_mood="energised",
        recent_reflection_days_ago=1,
        socratic_level=2,
        tutor_mode="standard",
    )
    block = render_context_block(ctx)
    assert "Land an AI engineering role" in block
    assert "[career_change]" in block
    assert "1 mastered" in block
    assert "2 proficient" in block
    assert "5 developing" in block
    assert "3 novice" in block
    assert "energised" in block
    assert "yesterday" in block
    assert "standard" in block.lower()


def test_render_long_goal_truncated_in_dataclass_not_here() -> None:
    # Truncation happens in _summarise_goal. render_context_block just prints
    # whatever it's given — so a caller-supplied long summary stays long.
    ctx = StudentContext(
        goal_summary="x" * 200,
        motivation=None,
        skill_distribution=SkillDistribution(proficient=1),
        recent_reflection_mood=None,
        recent_reflection_days_ago=None,
        socratic_level=0,
        tutor_mode="standard",
    )
    block = render_context_block(ctx)
    assert "x" * 200 in block


def test_render_reflection_today() -> None:
    ctx = StudentContext(
        goal_summary=None,
        motivation=None,
        skill_distribution=SkillDistribution(),
        recent_reflection_mood="stuck",
        recent_reflection_days_ago=0,
        socratic_level=0,
        tutor_mode="standard",
    )
    block = render_context_block(ctx)
    assert "stuck (today)" in block


def test_render_reflection_many_days_ago() -> None:
    ctx = StudentContext(
        goal_summary=None,
        motivation=None,
        skill_distribution=SkillDistribution(),
        recent_reflection_mood="calm",
        recent_reflection_days_ago=9,
        socratic_level=0,
        tutor_mode="standard",
    )
    block = render_context_block(ctx)
    assert "calm (9 days ago)" in block


def test_render_socratic_strict_surfaces_mode() -> None:
    ctx = StudentContext(
        goal_summary=None,
        motivation=None,
        skill_distribution=SkillDistribution(),
        recent_reflection_mood=None,
        recent_reflection_days_ago=None,
        socratic_level=3,
        tutor_mode="socratic_strict",
    )
    block = render_context_block(ctx)
    assert "Socratic level: strict" in block
    assert "socratic_strict" in block


def test_render_includes_memory_lines_when_present() -> None:
    ctx = StudentContext(
        goal_summary=None,
        motivation=None,
        skill_distribution=SkillDistribution(),
        recent_reflection_mood=None,
        recent_reflection_days_ago=None,
        socratic_level=0,
        tutor_mode="standard",
        recent_memories=[
            MemoryEntry(
                skill_slug="rag",
                skill_name="RAG",
                summary_text="chunking strategies",
                age_hours=4,
            )
        ],
    )
    block = render_context_block(ctx)
    assert "Recall on RAG" in block
    assert "chunking strategies" in block
    assert "4h ago" in block


def test_render_never_quote_instruction_present() -> None:
    # The "do not quote back" / calibration hint keeps the tutor from reciting
    # context at the student. It must be present regardless of state.
    for ctx in (_empty_ctx(),
                StudentContext(
                    goal_summary="g",
                    motivation=None,
                    skill_distribution=SkillDistribution(mastered=2),
                    recent_reflection_mood="proud",
                    recent_reflection_days_ago=0,
                    socratic_level=2,
                    tutor_mode="standard",
                )):
        block = render_context_block(ctx)
        assert "internal" in block.lower()
        assert "calibrate" in block.lower() or "do not quote" in block.lower()


# ── _bucket_skills ────────────────────────────────────────────────────────────


def _skill_row(level: str) -> UserSkillState:
    return UserSkillState(
        user_id=uuid.uuid4(),
        skill_id=uuid.uuid4(),
        mastery_level=level,
        confidence=0.5,
    )


def test_bucket_empty() -> None:
    dist = _bucket_skills([])
    assert dist.total == 0
    assert dist.novice == 0


def test_bucket_mixed_levels() -> None:
    rows = [
        _skill_row("novice"),
        _skill_row("novice"),
        _skill_row("developing"),
        _skill_row("proficient"),
        _skill_row("mastered"),
        _skill_row("unknown"),
    ]
    dist = _bucket_skills(rows)
    assert dist.novice == 2
    assert dist.developing == 1
    assert dist.proficient == 1
    assert dist.mastered == 1
    assert dist.unknown == 1
    assert dist.total == 6


def test_bucket_case_insensitive() -> None:
    # A seed or import path might upper-case these. Should still bucket right.
    rows = [_skill_row("NOVICE"), _skill_row("Mastered")]
    dist = _bucket_skills(rows)
    assert dist.novice == 1
    assert dist.mastered == 1


def test_bucket_unrecognised_goes_to_unknown() -> None:
    rows = [_skill_row("ninja"), _skill_row("")]
    dist = _bucket_skills(rows)
    assert dist.unknown == 2
    assert dist.novice == 0


# ── _reflection_age_days ──────────────────────────────────────────────────────


def test_reflection_age_none() -> None:
    assert _reflection_age_days(None, datetime.now(UTC)) is None


def test_reflection_age_from_date_today() -> None:
    now = datetime(2026, 4, 18, 15, 0, tzinfo=UTC)
    assert _reflection_age_days(date(2026, 4, 18), now) == 0


def test_reflection_age_from_date_past() -> None:
    now = datetime(2026, 4, 18, tzinfo=UTC)
    assert _reflection_age_days(date(2026, 4, 10), now) == 8


def test_reflection_age_from_datetime_naive() -> None:
    # Naive datetimes must be treated as UTC rather than crashing.
    now = datetime(2026, 4, 18, tzinfo=UTC)
    naive = datetime(2026, 4, 17)
    assert _reflection_age_days(naive, now) == 1


def test_reflection_age_future_safe() -> None:
    # Shouldn't produce negative numbers — clamp to 0. (Protects against
    # local-timezone edge cases where today's reflection was stored with a
    # +offset date that appears "ahead" of UTC midnight.)
    now = datetime(2026, 4, 18, tzinfo=UTC)
    tomorrow = now + timedelta(days=1)
    assert _reflection_age_days(tomorrow, now) == 0
