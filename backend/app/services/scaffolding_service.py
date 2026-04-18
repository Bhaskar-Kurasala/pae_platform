"""Scaffolding-decay service (P2-01).

Maps a user's confidence in a specific skill to a scaffolding level. The tutor
uses this level to decide how much hand-holding to offer — high for novices,
low for students the system believes have internalised the skill.

Decay: if the skill has not been touched in >14 days, we treat the student as
less confident than the stored value suggests (skill fades without practice).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_skill_state import UserSkillState

DECAY_AFTER_DAYS = 14
DECAY_FACTOR = 0.7  # multiply confidence by this if stale
MEDIUM_FLOOR = 0.3
LOW_FLOOR = 0.7


@dataclass(frozen=True)
class ScaffoldingLevel:
    label: str  # "high" | "medium" | "low"
    effective_confidence: float
    raw_confidence: float
    decayed: bool
    prompt_fragment: str


_HIGH = (
    "The student is a novice on this skill (low confidence). Offer generous "
    "scaffolding: walk through the problem step by step, name the sub-parts, "
    "and give one concrete worked hint. Still ask at least one question to check "
    "understanding."
)
_MEDIUM = (
    "The student has intermediate familiarity with this skill. Give at most one "
    "direct hint, then pivot to a guiding question that makes them do the work. "
    "Avoid fully solving the problem for them."
)
_LOW = (
    "The student has demonstrated competence on this skill. Do NOT provide "
    "direct hints or solution steps. Respond with one terse, sharp question "
    "that forces them to retrieve the answer themselves. Let them struggle a "
    "little — that is the point."
)


def _classify(confidence: float) -> tuple[str, str]:
    if confidence < MEDIUM_FLOOR:
        return "high", _HIGH
    if confidence < LOW_FLOOR:
        return "medium", _MEDIUM
    return "low", _LOW


def compute_level(
    raw_confidence: float,
    last_touched_at: datetime | None,
    *,
    now: datetime | None = None,
) -> ScaffoldingLevel:
    """Pure function — no DB. Used directly by tests and by the async loader below."""
    now = now or datetime.now(UTC)
    decayed = False
    effective = max(0.0, min(1.0, raw_confidence))
    if last_touched_at is not None:
        lt = last_touched_at if last_touched_at.tzinfo else last_touched_at.replace(tzinfo=UTC)
        if now - lt > timedelta(days=DECAY_AFTER_DAYS):
            effective = effective * DECAY_FACTOR
            decayed = True
    label, fragment = _classify(effective)
    return ScaffoldingLevel(
        label=label,
        effective_confidence=effective,
        raw_confidence=raw_confidence,
        decayed=decayed,
        prompt_fragment=fragment,
    )


async def load_level(
    db: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID
) -> ScaffoldingLevel:
    """Look up the user's state for this skill and return a scaffolding level.

    If no state exists, the student is treated as a total novice (high scaffolding).
    """
    state = (
        await db.execute(
            select(UserSkillState).where(
                UserSkillState.user_id == user_id,
                UserSkillState.skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    if state is None:
        return compute_level(0.0, None)
    return compute_level(state.confidence, state.last_touched_at)
