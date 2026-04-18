import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.skill_edge import SkillEdge
from app.models.user import User
from app.models.user_skill_state import UserSkillState


class SkillService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_graph(self) -> tuple[list[Skill], list[SkillEdge]]:
        skills = list((await self.db.execute(select(Skill))).scalars().all())
        edges = list((await self.db.execute(select(SkillEdge))).scalars().all())
        return skills, edges

    async def list_user_states(self, user: User) -> list[UserSkillState]:
        rows = (
            await self.db.execute(
                select(UserSkillState).where(UserSkillState.user_id == user.id)
            )
        ).scalars().all()
        return list(rows)

    async def touch(self, user: User, skill_id: uuid.UUID) -> UserSkillState | None:
        """Upsert user_skill_state.last_touched_at = now.

        Returns None if the skill does not exist.
        """
        skill = (
            await self.db.execute(select(Skill).where(Skill.id == skill_id))
        ).scalar_one_or_none()
        if skill is None:
            return None

        now = datetime.now(UTC)
        state = (
            await self.db.execute(
                select(UserSkillState).where(
                    UserSkillState.user_id == user.id,
                    UserSkillState.skill_id == skill_id,
                )
            )
        ).scalar_one_or_none()

        if state is None:
            state = UserSkillState(
                user_id=user.id,
                skill_id=skill_id,
                mastery_level="novice",
                confidence=0.1,
                last_touched_at=now,
            )
            self.db.add(state)
        else:
            state.last_touched_at = now

        await self.db.commit()
        await self.db.refresh(state)
        return state
