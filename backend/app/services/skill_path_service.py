from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.skill_edge import SkillEdge

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
