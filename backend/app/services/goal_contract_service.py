import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal_contract import GoalContract
from app.models.user import User
from app.schemas.goal_contract import GoalContractCreate, GoalContractUpdate

log = structlog.get_logger()


class GoalContractService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_user(self, user: User) -> GoalContract | None:
        result = await self.db.execute(
            select(GoalContract).where(GoalContract.user_id == user.id)
        )
        return result.scalar_one_or_none()

    async def upsert_for_user(
        self, user: User, payload: GoalContractCreate
    ) -> tuple[GoalContract, bool]:
        """Create or update the user's single goal contract.

        Returns (contract, created) where created=True if a new row was inserted.
        """
        existing = await self.get_for_user(user)
        if existing is not None:
            existing.motivation = payload.motivation
            existing.deadline_months = payload.deadline_months
            existing.success_statement = payload.success_statement
            await self.db.flush()
            await self.db.refresh(existing)
            log.info(
                "goal.updated",
                user_id=str(user.id),
                motivation=payload.motivation,
                deadline_months=payload.deadline_months,
            )
            return existing, False

        contract = GoalContract(
            user_id=user.id,
            motivation=payload.motivation,
            deadline_months=payload.deadline_months,
            success_statement=payload.success_statement,
        )
        self.db.add(contract)
        await self.db.flush()
        await self.db.refresh(contract)
        log.info(
            "goal.created",
            user_id=str(user.id),
            motivation=payload.motivation,
            deadline_months=payload.deadline_months,
        )
        return contract, True

    async def patch_for_user(
        self, user: User, payload: GoalContractUpdate
    ) -> GoalContract | None:
        existing = await self.get_for_user(user)
        if existing is None:
            return None
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return existing
        for field, value in updates.items():
            setattr(existing, field, value)
        await self.db.flush()
        await self.db.refresh(existing)
        log.info(
            "goal.updated",
            user_id=str(user.id),
            fields=list(updates.keys()),
        )
        return existing
