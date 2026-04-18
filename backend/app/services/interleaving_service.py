"""Interleaving suggestions (P3 3B #85).

Deterministic rule: if the student's last N exercise submissions were
all in the same skill, suggest moving to an adjacent skill to fight
the "blocked practice" illusion of mastery.

Pure helpers at the top (so the rule can be tested without a DB);
async loaders below pull the actual rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.skill import Skill
from app.models.skill_edge import SkillEdge

_CONSECUTIVE_THRESHOLD = 3
_SUBMISSION_LOOKBACK = 5


@dataclass(frozen=True)
class InterleavingSuggestion:
    suggest: bool
    current_skill_id: UUID | None
    next_skill_id: UUID | None
    reason: str


def should_interleave(
    recent_skill_ids: Sequence[UUID | None],
    *,
    threshold: int = _CONSECUTIVE_THRESHOLD,
) -> bool:
    """True iff the most recent `threshold` submissions share one skill.

    Missing (None) skill ids short-circuit to False — we don't want to
    fire the prompt off the back of unlabeled exercises.
    """
    if len(recent_skill_ids) < threshold:
        return False
    window = recent_skill_ids[:threshold]
    first = window[0]
    if first is None:
        return False
    return all(sid == first for sid in window)


def pick_adjacent_skill(
    current_skill_id: UUID,
    edges: Iterable[tuple[UUID, UUID, str]],
    *,
    already_recent: set[UUID] | None = None,
) -> UUID | None:
    """Choose the best next skill from the student's graph.

    Preference order:
    1. A `related` edge out of the current skill.
    2. A `related` edge *into* the current skill (sibling in the graph).
    3. None — caller falls back to "no suggestion yet".

    `already_recent` lets the caller exclude skills the student is
    already saturated on (e.g., the *current* skill trivially, plus any
    adjacent skill they already hammered earlier this week).
    """
    exclude = set(already_recent or set())
    exclude.add(current_skill_id)

    related_out: list[UUID] = []
    related_in: list[UUID] = []
    for src, dst, kind in edges:
        if kind != "related":
            continue
        if src == current_skill_id and dst not in exclude:
            related_out.append(dst)
        elif dst == current_skill_id and src not in exclude:
            related_in.append(src)

    if related_out:
        return related_out[0]
    if related_in:
        return related_in[0]
    return None


async def _recent_skill_ids(
    db: AsyncSession, *, user_id: UUID, limit: int = _SUBMISSION_LOOKBACK
) -> list[UUID | None]:
    result = await db.execute(
        select(Exercise.skill_id)
        .join(ExerciseSubmission, ExerciseSubmission.exercise_id == Exercise.id)
        .where(ExerciseSubmission.student_id == user_id)
        .order_by(desc(ExerciseSubmission.created_at))
        .limit(limit)
    )
    return [row[0] for row in result.all()]


async def _edges_touching(
    db: AsyncSession, *, skill_id: UUID
) -> list[tuple[UUID, UUID, str]]:
    result = await db.execute(
        select(SkillEdge.from_skill_id, SkillEdge.to_skill_id, SkillEdge.edge_type).where(
            (SkillEdge.from_skill_id == skill_id)
            | (SkillEdge.to_skill_id == skill_id)
        )
    )
    return [(r[0], r[1], r[2]) for r in result.all()]


async def _fetch_skill(db: AsyncSession, skill_id: UUID) -> Skill | None:
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    return result.scalar_one_or_none()


async def compute_suggestion(
    db: AsyncSession, *, user_id: UUID
) -> InterleavingSuggestion:
    recent = await _recent_skill_ids(db, user_id=user_id)
    if not should_interleave(recent):
        return InterleavingSuggestion(
            suggest=False,
            current_skill_id=None,
            next_skill_id=None,
            reason="Not enough consecutive same-skill practice yet",
        )

    current = recent[0]
    assert current is not None  # should_interleave guarantees this
    edges = await _edges_touching(db, skill_id=current)
    recent_set = {sid for sid in recent if sid is not None}
    next_id = pick_adjacent_skill(current, edges, already_recent=recent_set)

    if next_id is None:
        return InterleavingSuggestion(
            suggest=False,
            current_skill_id=current,
            next_skill_id=None,
            reason="No adjacent skill available to interleave",
        )

    return InterleavingSuggestion(
        suggest=True,
        current_skill_id=current,
        next_skill_id=next_id,
        reason="You've done 3 in a row on this skill — try something related",
    )


# Re-export for tests that want the dataclass without the async layer.
__all__ = [
    "InterleavingSuggestion",
    "compute_suggestion",
    "pick_adjacent_skill",
    "should_interleave",
]

# Silence unused-import warning — aliased is kept for future multi-skill joins.
_ = aliased
