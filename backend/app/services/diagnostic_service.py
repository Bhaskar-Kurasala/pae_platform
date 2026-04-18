import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.schemas.diagnostic import DiagnosticSubmission

BANK_PATH = Path(__file__).resolve().parents[1] / "seeds" / "diagnostic_questions.json"


def _load_bank() -> dict:
    with BANK_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_questions() -> dict:
    return _load_bank()


class DiagnosticService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def submit(
        self, user: User, submission: DiagnosticSubmission
    ) -> int:
        bank = _load_bank()
        scale = {item["rating"]: item for item in bank["scale"]}

        answer_by_slug = {a.skill_slug: a.rating for a in submission.answers}
        if not answer_by_slug:
            return 0

        skills = (
            await self.db.execute(
                select(Skill).where(Skill.slug.in_(list(answer_by_slug.keys())))
            )
        ).scalars().all()
        skill_by_slug = {s.slug: s for s in skills}

        existing_states = (
            await self.db.execute(
                select(UserSkillState).where(UserSkillState.user_id == user.id)
            )
        ).scalars().all()
        state_by_skill_id = {s.skill_id: s for s in existing_states}

        now = datetime.now(UTC)
        updated = 0
        for slug, rating in answer_by_slug.items():
            skill = skill_by_slug.get(slug)
            if skill is None:
                continue
            scale_entry = scale[rating]
            state = state_by_skill_id.get(skill.id)
            if state is None:
                state = UserSkillState(
                    user_id=user.id,
                    skill_id=skill.id,
                    mastery_level=scale_entry["mastery_level"],
                    confidence=scale_entry["confidence"],
                    last_touched_at=now,
                )
                self.db.add(state)
            else:
                state.mastery_level = scale_entry["mastery_level"]
                state.confidence = scale_entry["confidence"]
                state.last_touched_at = now
            updated += 1

        await self.db.commit()
        return updated
