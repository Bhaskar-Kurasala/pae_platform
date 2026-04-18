"""Student-state context service (P3 3A-1).

Every tutor call is mostly stateless per session. Before we add any prompt
behavior (disagreement, clarification, socratic intensity, etc.) the tutor
must first *see* the student: their active goal, skill distribution, recent
reflections, preferences. This module assembles a small 6-8 line context
block that the stream endpoint injects into the system prompt.

Design principles:
  - Pure builder (`render_context_block`) at the top — unit-testable without DB.
  - DB loader (`load_student_context`) is one-shot, bounded queries — no N+1.
  - Missing fields degrade gracefully. A new student still gets a useful (if
    brief) block rather than an empty string, so downstream prompt rules can
    rely on the section always existing.
  - The block is internal scaffolding; the tutor is told not to quote it back
    verbatim. Prompt integration adds the "do not echo" instruction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal_contract import GoalContract
from app.models.reflection import Reflection
from app.models.user_preferences import UserPreferences
from app.models.user_skill_state import UserSkillState
from app.services.conversation_memory_service import (
    MemoryEntry,
    load_recent_memories,
    render_memory_lines,
)

log = structlog.get_logger()


# Mastery bucket labels mirror the `mastery_level` string column so we can
# aggregate without loading the Skill table.
_MASTERY_BUCKETS: tuple[str, ...] = ("novice", "developing", "proficient", "mastered")


@dataclass(frozen=True)
class SkillDistribution:
    novice: int = 0
    developing: int = 0
    proficient: int = 0
    mastered: int = 0
    unknown: int = 0

    @property
    def total(self) -> int:
        return self.novice + self.developing + self.proficient + self.mastered + self.unknown


@dataclass(frozen=True)
class StudentContext:
    """All state a tutor needs to open a session well-informed."""

    goal_summary: str | None           # e.g. "Land an AI eng role in 6mo"
    motivation: str | None             # e.g. "career_change"
    skill_distribution: SkillDistribution
    recent_reflection_mood: str | None
    recent_reflection_days_ago: int | None
    socratic_level: int                # 0-3, 0 = off, 3 = strict
    tutor_mode: str                    # "standard" | "socratic_strict"
    # Top-N per-skill recall entries, freshest first (3A-2). Empty for new
    # students; rendered only when non-empty so the block stays concise.
    recent_memories: list[MemoryEntry] = field(default_factory=list)
    # Present for telemetry — which fields had to fall back to defaults.
    missing_fields: list[str] = field(default_factory=list)


# ── Pure rendering ──────────────────────────────────────────────────────────


def render_context_block(ctx: StudentContext) -> str:
    """Render StudentContext into a 6-8 line system-prompt fragment.

    Always returns a non-empty block. If every field is missing, the block
    still sets expectations ("new student — no history yet") so the tutor
    calibrates its opening appropriately.
    """
    lines: list[str] = ["---", "Student state (internal — do not quote back):"]

    if ctx.goal_summary:
        motivation_suffix = f" [{ctx.motivation}]" if ctx.motivation else ""
        lines.append(f"- Goal: {ctx.goal_summary}{motivation_suffix}")
    else:
        lines.append("- Goal: none set yet")

    dist = ctx.skill_distribution
    if dist.total == 0:
        lines.append("- Skills: no assessed skills yet (new learner)")
    else:
        parts: list[str] = []
        if dist.mastered:
            parts.append(f"{dist.mastered} mastered")
        if dist.proficient:
            parts.append(f"{dist.proficient} proficient")
        if dist.developing:
            parts.append(f"{dist.developing} developing")
        if dist.novice:
            parts.append(f"{dist.novice} novice")
        if not parts:
            parts.append(f"{dist.unknown} unassessed")
        lines.append(f"- Skills: {', '.join(parts)}")

    if ctx.recent_reflection_mood:
        age = ctx.recent_reflection_days_ago
        if age is None or age == 0:
            when = "today"
        elif age == 1:
            when = "yesterday"
        else:
            when = f"{age} days ago"
        lines.append(f"- Last reflection: {ctx.recent_reflection_mood} ({when})")
    else:
        lines.append("- Last reflection: none recorded")

    memory_lines = render_memory_lines(ctx.recent_memories)
    if memory_lines:
        lines.extend(memory_lines)

    if ctx.socratic_level > 0 or ctx.tutor_mode == "socratic_strict":
        level_label = {0: "off", 1: "gentle", 2: "standard", 3: "strict"}.get(
            ctx.socratic_level, "standard"
        )
        lines.append(
            f"- Socratic level: {level_label} "
            f"(mode={ctx.tutor_mode})"
        )
    else:
        lines.append("- Socratic level: off (mode=standard)")

    lines.append(
        "Use this to calibrate your opening — don't greet a ghost student "
        "the same way you greet an engaged one."
    )
    return "\n".join(lines)


def _summarise_goal(goal: GoalContract | None) -> tuple[str | None, str | None]:
    if goal is None:
        return None, None
    statement = (goal.success_statement or "").strip()
    if not statement:
        return None, goal.motivation
    summary = statement if len(statement) <= 120 else statement[:117] + "..."
    return f"{summary} (~{goal.deadline_months}mo)", goal.motivation


def _bucket_skills(rows: list[UserSkillState]) -> SkillDistribution:
    counts = {b: 0 for b in _MASTERY_BUCKETS}
    unknown = 0
    for row in rows:
        level = (row.mastery_level or "").lower()
        if level in counts:
            counts[level] += 1
        else:
            unknown += 1
    return SkillDistribution(
        novice=counts["novice"],
        developing=counts["developing"],
        proficient=counts["proficient"],
        mastered=counts["mastered"],
        unknown=unknown,
    )


def _reflection_age_days(
    reflection_date: datetime | None, now: datetime
) -> int | None:
    if reflection_date is None:
        return None
    # Reflection stores `date`, not datetime. Normalise to midnight UTC.
    if hasattr(reflection_date, "year") and not isinstance(reflection_date, datetime):
        ref_dt = datetime(
            reflection_date.year,
            reflection_date.month,
            reflection_date.day,
            tzinfo=UTC,
        )
    else:
        ref_dt = reflection_date  # already a datetime
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=UTC)
    return max(0, (now.date() - ref_dt.date()).days)


def _derive_socratic_level(prefs: UserPreferences | None) -> int:
    """Map the current boolean/string state into the 0-3 scale.

    3A-3 will add a proper column; until then derive from tutor_mode:
      - socratic_strict → 3
      - standard        → 0
    """
    if prefs is None:
        return 0
    if prefs.tutor_mode == "socratic_strict":
        return 3
    return 0


# ── DB loader ───────────────────────────────────────────────────────────────


async def load_student_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> StudentContext:
    """Load all student state needed to render the context block.

    Five bounded queries — goal (1 row), skills (capped), most recent
    reflection (1 row), preferences (1 row). No joins, no N+1.
    """
    current = now or datetime.now(UTC)
    missing: list[str] = []

    goal = (
        await db.execute(
            select(GoalContract).where(GoalContract.user_id == user_id)
        )
    ).scalar_one_or_none()
    goal_summary, motivation = _summarise_goal(goal)
    if goal is None:
        missing.append("goal")

    skill_rows = (
        await db.execute(
            select(UserSkillState)
            .where(UserSkillState.user_id == user_id)
            .order_by(desc(UserSkillState.last_touched_at))
            .limit(200)
        )
    ).scalars().all()
    skill_dist = _bucket_skills(list(skill_rows))
    if skill_dist.total == 0:
        missing.append("skills")

    latest_reflection = (
        await db.execute(
            select(Reflection)
            .where(Reflection.user_id == user_id)
            .order_by(desc(Reflection.reflection_date))
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_reflection is None:
        missing.append("reflections")
        mood = None
        age = None
    else:
        mood = latest_reflection.mood
        age = _reflection_age_days(latest_reflection.reflection_date, current)

    prefs = (
        await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user_id)
        )
    ).scalar_one_or_none()
    socratic_level = _derive_socratic_level(prefs)
    tutor_mode = prefs.tutor_mode if prefs is not None else "standard"
    if prefs is None:
        missing.append("preferences")

    memories = await load_recent_memories(db, user_id, limit=5, now=current)
    if not memories:
        missing.append("memories")

    return StudentContext(
        goal_summary=goal_summary,
        motivation=motivation,
        skill_distribution=skill_dist,
        recent_reflection_mood=mood,
        recent_reflection_days_ago=age,
        socratic_level=socratic_level,
        tutor_mode=tutor_mode,
        recent_memories=memories,
        missing_fields=missing,
    )


async def build_context_block(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> tuple[str, list[str]]:
    """Convenience wrapper: load + render. Returns (block, missing_fields).

    The stream endpoint uses this directly so it doesn't need to hold on to
    the StudentContext dataclass — it just wants the prompt fragment and the
    telemetry list.
    """
    ctx = await load_student_context(db, user_id, now=now)
    block = render_context_block(ctx)
    log.info(
        "tutor.context_injected",
        user_id=str(user_id),
        context_lines=block.count("\n") + 1,
        missing_fields=ctx.missing_fields,
        memories_loaded=len(ctx.recent_memories),
    )
    for mem in ctx.recent_memories:
        log.info(
            "tutor.memory_loaded",
            user_id=str(user_id),
            skill_slug=mem.skill_slug,
            memory_age_hours=mem.age_hours,
        )
    return block, ctx.missing_fields
