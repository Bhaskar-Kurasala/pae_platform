"""Pure tests for 3B #7 first-day plan helpers."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.services.first_day_plan_service import (
    build_plan,
    pick_starter_skills,
)


def _s(slug: str) -> tuple[UUID, str]:
    return (uuid4(), slug)


def test_pick_starters_are_skills_with_no_incoming_prereqs() -> None:
    a, b, c = _s("a"), _s("b"), _s("c")
    edges = [(a[0], b[0]), (b[0], c[0])]  # a → b → c
    starters = pick_starter_skills([a, b, c], edges)
    assert starters == [a]


def test_pick_starters_handles_forest() -> None:
    a, b, c, d = _s("a"), _s("b"), _s("c"), _s("d")
    # Two independent chains: a→b and c→d
    edges = [(a[0], b[0]), (c[0], d[0])]
    starters = pick_starter_skills([a, b, c, d], edges)
    assert set(s[1] for s in starters) == {"a", "c"}


def test_pick_starters_respects_limit() -> None:
    skills = [_s(f"s{i}") for i in range(10)]
    starters = pick_starter_skills(skills, [], limit=3)
    assert len(starters) == 3


def test_pick_starters_when_all_have_prereqs_returns_empty() -> None:
    a, b = _s("a"), _s("b")
    # cyclic-ish: both target each other
    edges = [(a[0], b[0]), (b[0], a[0])]
    assert pick_starter_skills([a, b], edges) == []


def test_build_plan_low_bucket_fits_day1_activities() -> None:
    starters = [_s("foundations")]
    plan = build_plan(starters, weekly_hours="3-5")
    # 35 min/day budget → lesson(20) + exercise(30)=50 exceeds, so only lesson.
    day1 = [a for a in plan.activities if a.day == 1]
    assert plan.daily_minutes_target == 35
    assert sum(a.minutes for a in day1) <= 35


def test_build_plan_mid_bucket_fits_lesson_plus_exercise_on_day1() -> None:
    starters = [_s("foundations")]
    plan = build_plan(starters, weekly_hours="6-10")
    day1 = [a for a in plan.activities if a.day == 1]
    kinds = {a.kind for a in day1}
    assert "lesson" in kinds
    assert "exercise" in kinds
    assert sum(a.minutes for a in day1) <= 70


def test_build_plan_introduces_second_skill_by_day3() -> None:
    a = _s("a")
    b = _s("b")
    plan = build_plan([a, b], weekly_hours="11+")
    day3 = [x for x in plan.activities if x.day == 3]
    slugs = {x.skill_slug for x in day3}
    assert "b" in slugs


def test_build_plan_respects_budget_on_all_three_days() -> None:
    starters = [_s("a"), _s("b")]
    plan = build_plan(starters, weekly_hours="6-10")
    for day in (1, 2, 3):
        budget = sum(a.minutes for a in plan.activities if a.day == day)
        assert budget <= 70


def test_build_plan_with_no_starter_is_empty() -> None:
    plan = build_plan([], weekly_hours="6-10")
    assert plan.activities == ()
    assert plan.daily_minutes_target == 70


def test_build_plan_uses_low_default_when_bucket_missing() -> None:
    starters = [_s("a")]
    plan = build_plan(starters, weekly_hours=None)
    assert plan.daily_minutes_target == 35


def test_build_plan_covers_three_days_when_budget_allows() -> None:
    starters = [_s("a"), _s("b")]
    plan = build_plan(starters, weekly_hours="11+")
    days = {a.day for a in plan.activities}
    assert days == {1, 2, 3}
