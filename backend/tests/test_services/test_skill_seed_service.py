import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.skill_edge import SkillEdge
from app.services.skill_seed_service import load_seed_data, seed_skill_graph


@pytest.mark.asyncio
async def test_seed_creates_skills_and_edges(db_session: AsyncSession) -> None:
    skills_added, edges_added = await seed_skill_graph(db_session)
    data = load_seed_data()

    assert skills_added == len(data["skills"])
    assert edges_added == len(data["edges"])

    skill_count = (await db_session.execute(select(func.count(Skill.id)))).scalar_one()
    edge_count = (await db_session.execute(select(func.count(SkillEdge.id)))).scalar_one()
    assert skill_count == len(data["skills"])
    assert edge_count == len(data["edges"])


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    await seed_skill_graph(db_session)
    skills_added_2, edges_added_2 = await seed_skill_graph(db_session)

    assert skills_added_2 == 0
    assert edges_added_2 == 0

    data = load_seed_data()
    skill_count = (await db_session.execute(select(func.count(Skill.id)))).scalar_one()
    edge_count = (await db_session.execute(select(func.count(SkillEdge.id)))).scalar_one()
    assert skill_count == len(data["skills"])
    assert edge_count == len(data["edges"])


@pytest.mark.asyncio
async def test_seed_slugs_unique(db_session: AsyncSession) -> None:
    data = load_seed_data()
    slugs = [s["slug"] for s in data["skills"]]
    assert len(slugs) == len(set(slugs)), "seed has duplicate slugs"


@pytest.mark.asyncio
async def test_seed_edges_reference_known_skills(db_session: AsyncSession) -> None:
    data = load_seed_data()
    slugs = {s["slug"] for s in data["skills"]}
    for edge in data["edges"]:
        assert edge["from"] in slugs, f"unknown from: {edge['from']}"
        assert edge["to"] in slugs, f"unknown to: {edge['to']}"
        assert edge["from"] != edge["to"], f"self-loop: {edge}"
        assert edge["type"] in {"prereq", "related"}, f"bad type: {edge['type']}"
