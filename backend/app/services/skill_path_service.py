from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saved_skill_path import SavedSkillPath
from app.models.skill import Skill
from app.models.skill_edge import SkillEdge
from app.schemas.skill_path import SavedPathResponse

log = structlog.get_logger()

MOTIVATION_TARGETS: dict[str, list[str]] = {
    "career_switch": [
        "claude-api",
        "rag-basics",
        "agent-design",
        "langgraph",
        "multi-agent",
        "eval-harness",
        "production-deploy",
    ],
    "skill_up": [
        "claude-api",
        "rag-basics",
        "agent-design",
        "langgraph",
        "eval-harness",
        "cost-optimization",
        "production-deploy",
    ],
    "interview": [
        "fastapi",
        "llm-fundamentals",
        "claude-api",
        "rag-basics",
        "agent-design",
        "eval-harness",
    ],
    "curiosity": [
        "llm-fundamentals",
        "prompt-engineering",
        "claude-api",
        "rag-basics",
        "agent-design",
    ],
}

DEFAULT_TARGETS = MOTIVATION_TARGETS["skill_up"]


class SkillPathService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def compute_path_slugs(self, motivation: str | None) -> list[str]:
        targets = MOTIVATION_TARGETS.get(motivation or "", DEFAULT_TARGETS)

        skills = (await self.db.execute(select(Skill))).scalars().all()
        slug_by_id = {s.id: s.slug for s in skills}
        id_by_slug = {s.slug: s.id for s in skills}

        edges = (await self.db.execute(select(SkillEdge))).scalars().all()
        prereq_parents: dict[str, list[str]] = {}
        for e in edges:
            if e.edge_type != "prereq":
                continue
            child = slug_by_id.get(e.to_skill_id)
            parent = slug_by_id.get(e.from_skill_id)
            if child is None or parent is None:
                continue
            prereq_parents.setdefault(child, []).append(parent)

        visited: set[str] = set()
        queue = [t for t in targets if t in id_by_slug]
        while queue:
            cur = queue.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for parent in prereq_parents.get(cur, []):
                if parent not in visited:
                    queue.append(parent)
        return sorted(visited)


# ── #24 Path saving ────────────────────────────────────────────────────────────


async def save_skill_path(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    skill_ids: list[uuid.UUID],
) -> None:
    """Upsert the student's manually saved learning path."""
    result = await db.execute(select(SavedSkillPath).where(SavedSkillPath.user_id == user_id))
    record = result.scalar_one_or_none()
    serialized = json.dumps([str(sid) for sid in skill_ids])
    if record is None:
        record = SavedSkillPath(user_id=user_id, skill_ids_json=serialized)
        db.add(record)
    else:
        record.skill_ids_json = serialized
    await db.commit()
    log.info("skillmap.path_saved", user_id=str(user_id), skill_count=len(skill_ids))


async def get_saved_skill_path(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> SavedPathResponse | None:
    """Return the student's saved path, or None if not set."""
    result = await db.execute(select(SavedSkillPath).where(SavedSkillPath.user_id == user_id))
    record = result.scalar_one_or_none()
    if record is None:
        return None
    raw: list[str] = json.loads(record.skill_ids_json)
    return SavedPathResponse(
        user_id=user_id,
        skill_ids=[uuid.UUID(s) for s in raw],
    )
