import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.skill_edge import SkillEdge

SEED_PATH = Path(__file__).resolve().parents[1] / "seeds" / "skill_graph.json"


def load_seed_data() -> dict:
    with SEED_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


async def seed_skill_graph(session: AsyncSession) -> tuple[int, int]:
    """Idempotent skill graph seed.

    Returns (skills_added, edges_added). Existing rows are left untouched.
    """
    data = load_seed_data()

    existing_slugs = {
        row[0]
        for row in (await session.execute(select(Skill.slug))).all()
    }

    skills_added = 0
    for item in data["skills"]:
        if item["slug"] in existing_slugs:
            continue
        session.add(
            Skill(
                slug=item["slug"],
                name=item["name"],
                description=item.get("description", ""),
                difficulty=item.get("difficulty", 1),
            )
        )
        skills_added += 1

    await session.flush()

    slug_to_id = {
        row[0]: row[1]
        for row in (await session.execute(select(Skill.slug, Skill.id))).all()
    }

    existing_edges = {
        (row[0], row[1], row[2])
        for row in (
            await session.execute(
                select(SkillEdge.from_skill_id, SkillEdge.to_skill_id, SkillEdge.edge_type)
            )
        ).all()
    }

    edges_added = 0
    for edge in data["edges"]:
        from_id = slug_to_id.get(edge["from"])
        to_id = slug_to_id.get(edge["to"])
        if from_id is None or to_id is None:
            continue
        key = (from_id, to_id, edge["type"])
        if key in existing_edges:
            continue
        session.add(
            SkillEdge(from_skill_id=from_id, to_skill_id=to_id, edge_type=edge["type"])
        )
        edges_added += 1

    await session.commit()
    return skills_added, edges_added
