"""First-day plan (P3 3B #7).

After onboarding, generate a 3-day starter plan combining:

1. The student's `weekly_hours` bucket → target daily minutes
   (via `goal_contract_service.daily_minutes_target`).
2. The top-of-graph "starter" skills — skills with no `prereq` edges
   pointing into them (roots of the skill DAG).

The output is intentionally lightweight: day 1/2/3 with 2-3 activities
each, respecting the daily-minutes budget. The Today screen renders
this as the student's starting point.

Pure helpers on top, async loaders below.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.skill_edge import SkillEdge
from app.services.goal_contract_service import daily_minutes_target

_PLAN_DAYS = 3
_LESSON_MINUTES = 20
_EXERCISE_MINUTES = 30
_REVIEW_MINUTES = 10


@dataclass(frozen=True)
class PlannedActivity:
    day: int
    kind: str  # "lesson" | "exercise" | "review"
    skill_id: UUID
    skill_slug: str
    minutes: int
    rationale: str


@dataclass(frozen=True)
class FirstDayPlan:
    daily_minutes_target: int
    activities: tuple[PlannedActivity, ...]


def pick_starter_skills(
    all_skills: Iterable[tuple[UUID, str]],
    prereq_edges: Iterable[tuple[UUID, UUID]],
    *,
    limit: int = 3,
) -> list[tuple[UUID, str]]:
    """Skills that have no incoming prereq edge — roots of the DAG."""
    targets = {dst for _src, dst in prereq_edges}
    roots = [(sid, slug) for sid, slug in all_skills if sid not in targets]
    return roots[:limit]


def _activities_for_day(
    day: int,
    skills: list[tuple[UUID, str]],
    *,
    minutes_budget: int,
) -> list[PlannedActivity]:
    """Build one day's activities, spending at most `minutes_budget` mins.

    Pattern: one lesson + one exercise on day 1 (foundation); day 2 adds
    a review; day 3 introduces the second starter skill.
    """
    if not skills:
        return []
    primary = skills[0]
    out: list[PlannedActivity] = []
    spent = 0

    def _push(kind: str, skill: tuple[UUID, str], minutes: int, why: str) -> None:
        nonlocal spent
        if spent + minutes > minutes_budget:
            return
        out.append(
            PlannedActivity(
                day=day,
                kind=kind,
                skill_id=skill[0],
                skill_slug=skill[1],
                minutes=minutes,
                rationale=why,
            )
        )
        spent += minutes

    if day == 1:
        _push("lesson", primary, _LESSON_MINUTES, "Start with the foundation")
        _push("exercise", primary, _EXERCISE_MINUTES, "Apply what you just learned")
    elif day == 2:
        _push("review", primary, _REVIEW_MINUTES, "Short review of yesterday")
        _push("exercise", primary, _EXERCISE_MINUTES, "Second rep — retrieval practice")
        if len(skills) > 1:
            _push(
                "lesson",
                skills[1],
                _LESSON_MINUTES,
                "Preview the next starter skill",
            )
    else:  # day 3
        if len(skills) > 1:
            _push(
                "exercise",
                skills[1],
                _EXERCISE_MINUTES,
                "First-attempt exercise on skill two",
            )
        _push("review", primary, _REVIEW_MINUTES, "Lock-in review")
        _push(
            "lesson",
            primary,
            _LESSON_MINUTES,
            "Deeper lesson on the foundation skill",
        )

    return out


def build_plan(
    starter_skills: list[tuple[UUID, str]],
    *,
    weekly_hours: str | None,
    days: int = _PLAN_DAYS,
) -> FirstDayPlan:
    target = daily_minutes_target(weekly_hours)
    activities: list[PlannedActivity] = []
    for day in range(1, days + 1):
        activities.extend(
            _activities_for_day(day, starter_skills, minutes_budget=target)
        )
    return FirstDayPlan(
        daily_minutes_target=target, activities=tuple(activities)
    )


async def _load_starter_skills(
    db: AsyncSession, *, limit: int = 3
) -> list[tuple[UUID, str]]:
    skills_res = await db.execute(select(Skill.id, Skill.slug))
    all_skills = [(row[0], row[1]) for row in skills_res.all()]
    edges_res = await db.execute(
        select(SkillEdge.from_skill_id, SkillEdge.to_skill_id).where(
            SkillEdge.edge_type == "prereq"
        )
    )
    prereq_edges = [(row[0], row[1]) for row in edges_res.all()]
    return pick_starter_skills(all_skills, prereq_edges, limit=limit)


async def build_first_day_plan(
    db: AsyncSession, *, weekly_hours: str | None
) -> FirstDayPlan:
    starter = await _load_starter_skills(db)
    return build_plan(starter, weekly_hours=weekly_hours)


__all__ = [
    "FirstDayPlan",
    "PlannedActivity",
    "build_first_day_plan",
    "build_plan",
    "pick_starter_skills",
]
