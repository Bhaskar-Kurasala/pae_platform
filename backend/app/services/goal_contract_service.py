from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal_contract import GoalContract
from app.models.user import User
from app.schemas.goal_contract import GoalContractCreate, GoalContractUpdate

DAYS_PER_MONTH = 30


def days_remaining(contract: GoalContract, *, now: datetime | None = None) -> int:
    """Days left until the goal deadline, floored at 0.

    Computed from `created_at + deadline_months * 30 days - now`. Naïve but
    explicit — calendar months would inflate variance for the same input.
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    created = contract.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    deadline_total_days = int(contract.deadline_months) * DAYS_PER_MONTH
    elapsed_days = (current - created).days
    return max(0, deadline_total_days - elapsed_days)

log = structlog.get_logger()


# P3 3B #5: convert bucket → target daily minutes for planning heuristics.
# Conservative midpoints ÷ 7 so we don't over-schedule the student.
_WEEKLY_HOURS_TO_DAILY_MINUTES = {
    "3-5": 35,      # ~4 hrs/wk → ~35 min/day
    "6-10": 70,     # ~8 hrs/wk → ~70 min/day
    "11+": 110,     # floor of 11 hrs/wk → ~95 min/day, rounded up to 110
}


def daily_minutes_target(weekly_hours: str | None) -> int:
    """Approximate daily study minutes for a weekly-hours bucket.

    Returns 35 (the low bucket default) when the student hasn't picked one
    yet — we'd rather under-schedule and nudge up than burn them out.
    """
    if weekly_hours is None:
        return _WEEKLY_HOURS_TO_DAILY_MINUTES["3-5"]
    return _WEEKLY_HOURS_TO_DAILY_MINUTES.get(
        weekly_hours, _WEEKLY_HOURS_TO_DAILY_MINUTES["3-5"]
    )


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
            existing.weekly_hours = payload.weekly_hours
            existing.target_role = payload.target_role
            await self.db.flush()
            await self.db.refresh(existing)
            log.info(
                "goal.updated",
                user_id=str(user.id),
                motivation=payload.motivation,
                deadline_months=payload.deadline_months,
                weekly_hours=payload.weekly_hours,
            )
            return existing, False

        contract = GoalContract(
            user_id=user.id,
            motivation=payload.motivation,
            deadline_months=payload.deadline_months,
            success_statement=payload.success_statement,
            weekly_hours=payload.weekly_hours,
            target_role=payload.target_role,
        )
        self.db.add(contract)
        await self.db.flush()
        await self.db.refresh(contract)
        log.info(
            "goal.created",
            user_id=str(user.id),
            motivation=payload.motivation,
            deadline_months=payload.deadline_months,
            weekly_hours=payload.weekly_hours,
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
