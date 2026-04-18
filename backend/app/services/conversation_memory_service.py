"""Conversation memory service (P3 3A-2).

Per-(user, skill) rolling summaries. One row per pair; upsert overwrites.
The tutor loads the top-N most-recent entries at session open so it doesn't
re-introduce a concept the student already worked through.

Pure helpers at the top (age bucketing, summary trimming) are unit-testable
without a DB; the async functions handle persistence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_memory import ConversationMemory
from app.models.skill import Skill

log = structlog.get_logger()


# Tutors stay focused when summaries are short; trimming here keeps the
# rendered block inside the 6-10-line budget even with 5 memories loaded.
_SUMMARY_MAX_CHARS = 180


@dataclass(frozen=True)
class MemoryEntry:
    """Hydrated memory row for rendering."""

    skill_slug: str
    skill_name: str
    summary_text: str
    age_hours: int


def _trim_summary(text: str, limit: int = _SUMMARY_MAX_CHARS) -> str:
    """Trim to `limit` chars on a word boundary when possible."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _age_hours(last_updated: datetime | None, now: datetime) -> int:
    """Hours since last_updated, clamped to >= 0 and naive-safe."""
    if last_updated is None:
        return 0
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=UTC)
    delta = now - last_updated
    return max(0, int(delta.total_seconds() // 3600))


def render_memory_lines(entries: list[MemoryEntry]) -> list[str]:
    """Render loaded memories as 1-5 student-context lines.

    Returns `[]` when empty so `render_context_block` can skip the section.
    Format: `- Recall on {skill_name}: {summary} ({age})` — age as "3h ago",
    "2d ago", or "new" when freshly written.
    """
    lines: list[str] = []
    for entry in entries:
        age_label = _format_age(entry.age_hours)
        lines.append(
            f"- Recall on {entry.skill_name}: {entry.summary_text} ({age_label})"
        )
    return lines


def _format_age(age_hours: int) -> str:
    if age_hours <= 0:
        return "just now"
    if age_hours < 24:
        return f"{age_hours}h ago"
    days = age_hours // 24
    return f"{days}d ago"


# ── DB access ───────────────────────────────────────────────────────────────


async def load_recent_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 5,
    now: datetime | None = None,
) -> list[MemoryEntry]:
    """Return the top-`limit` most-recent memories for a user, hydrated with
    skill slug + name. No joins are used — two bounded queries keep this path
    cheap on the tutor hot-path.
    """
    current = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(ConversationMemory)
            .where(ConversationMemory.user_id == user_id)
            .order_by(desc(ConversationMemory.last_updated))
            .limit(max(1, limit))
        )
    ).scalars().all()
    if not rows:
        return []

    skill_ids = [row.skill_id for row in rows]
    skill_rows = (
        await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))
    ).scalars().all()
    skill_map = {s.id: s for s in skill_rows}

    entries: list[MemoryEntry] = []
    for row in rows:
        skill = skill_map.get(row.skill_id)
        if skill is None:
            # Skill was deleted but memory row lingered. Skip — referencing a
            # dangling skill would confuse the tutor more than omitting it.
            continue
        entries.append(
            MemoryEntry(
                skill_slug=skill.slug,
                skill_name=skill.name,
                summary_text=_trim_summary(row.summary_text),
                age_hours=_age_hours(row.last_updated, current),
            )
        )
    return entries


async def upsert_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    skill_id: uuid.UUID,
    summary_text: str,
    *,
    now: datetime | None = None,
) -> ConversationMemory:
    """Write or update the (user, skill) memory row.

    No commit — caller owns the transaction so memory writes can be batched
    with other end-of-turn state updates.
    """
    current = now or datetime.now(UTC)
    existing = (
        await db.execute(
            select(ConversationMemory).where(
                ConversationMemory.user_id == user_id,
                ConversationMemory.skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    trimmed = _trim_summary(summary_text)
    if existing is None:
        row = ConversationMemory(
            user_id=user_id,
            skill_id=skill_id,
            summary_text=trimmed,
            last_updated=current,
        )
        db.add(row)
        log.info(
            "tutor.memory_written",
            user_id=str(user_id),
            skill_id=str(skill_id),
            new=True,
        )
        return row
    existing.summary_text = trimmed
    existing.last_updated = current
    log.info(
        "tutor.memory_written",
        user_id=str(user_id),
        skill_id=str(skill_id),
        new=False,
    )
    return existing
