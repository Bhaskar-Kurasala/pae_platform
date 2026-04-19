"""Today screen API (P3 3A-11 and following).

Thin route surface for the student's "Today" workspace — intention
prompt first, with sibling tickets adding micro-wins, end-of-day
reflection, and stuck-intervention banners over time.
"""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.consistency import ConsistencyResponse
from app.schemas.daily_intention import (
    DailyIntentionCreate,
    DailyIntentionResponse,
)
from app.schemas.first_day_plan import FirstDayPlanResponse, PlannedActivityItem
from app.schemas.micro_wins import MicroWinItem, MicroWinsResponse
from app.schemas.weekly_intention import (
    WeeklyIntentionCreate,
    WeeklyIntentionItem,
    WeeklyIntentionsResponse,
)
from app.services.consistency_service import load_consistency
from app.services.daily_intention_service import (
    get_for_date,
    today_in_utc,
    upsert_today,
)
from app.services.first_day_plan_service import build_first_day_plan
from app.services.goal_contract_service import GoalContractService
from app.services.micro_wins_service import load_micro_wins
from app.services.weekly_intention_service import (
    current_week_starting,
    load_weekly_intentions,
    upsert_weekly_intentions,
)

log = structlog.get_logger()

router = APIRouter(prefix="/today", tags=["today"])


@router.post("/intention", response_model=DailyIntentionResponse)
async def set_today_intention(
    payload: DailyIntentionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyIntentionResponse:
    """Set or overwrite today's intention for the current user."""
    row = await upsert_today(
        db,
        user_id=current_user.id,
        text=payload.text,
        intention_date=payload.intention_date,
    )
    return DailyIntentionResponse.model_validate(row)


@router.get("/intention", response_model=DailyIntentionResponse | None)
async def get_today_intention(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyIntentionResponse | None:
    """Return today's intention for the current user, or null if unset."""
    row = await get_for_date(
        db, user_id=current_user.id, on=today_in_utc()
    )
    return DailyIntentionResponse.model_validate(row) if row else None


@router.get("/consistency", response_model=ConsistencyResponse)
async def get_today_consistency(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConsistencyResponse:
    """Days-of-last-7 the student did anything (P3 3A-14)."""
    days_active, window_days = await load_consistency(
        db, user_id=current_user.id
    )
    log.info(
        "today.consistency_shown",
        user_id=str(current_user.id),
        days_this_week=days_active,
    )
    return ConsistencyResponse(
        days_this_week=days_active, window_days=window_days
    )


@router.post("/weekly-intentions", response_model=WeeklyIntentionsResponse)
async def set_weekly_intentions(
    payload: WeeklyIntentionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WeeklyIntentionsResponse:
    """Set or replace this week's 1-3 focus items (P3 3B #151)."""
    rows = await upsert_weekly_intentions(
        db, user_id=current_user.id, items=payload.items
    )
    log.info(
        "today.weekly_intentions_set",
        user_id=str(current_user.id),
        count=len(rows),
    )
    return WeeklyIntentionsResponse(
        week_starting=current_week_starting(),
        items=[WeeklyIntentionItem.model_validate(r) for r in rows],
    )


@router.get("/weekly-intentions", response_model=WeeklyIntentionsResponse)
async def get_weekly_intentions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WeeklyIntentionsResponse:
    rows = await load_weekly_intentions(db, user_id=current_user.id)
    return WeeklyIntentionsResponse(
        week_starting=current_week_starting(),
        items=[WeeklyIntentionItem.model_validate(r) for r in rows],
    )


@router.get("/first-day-plan", response_model=FirstDayPlanResponse)
async def get_first_day_plan(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FirstDayPlanResponse:
    """3-day starter plan from skill graph + weekly-hours (P3 3B #7)."""
    contract = await GoalContractService(db).get_for_user(current_user)
    weekly_hours = contract.weekly_hours if contract else None
    plan = await build_first_day_plan(db, weekly_hours=weekly_hours)
    log.info(
        "onboarding.first_day_plan_generated",
        user_id=str(current_user.id),
        daily_minutes=plan.daily_minutes_target,
        activities=len(plan.activities),
    )
    return FirstDayPlanResponse(
        daily_minutes_target=plan.daily_minutes_target,
        activities=[
            PlannedActivityItem(
                day=a.day,
                kind=a.kind,
                skill_id=a.skill_id,
                skill_slug=a.skill_slug,
                minutes=a.minutes,
                rationale=a.rationale,
            )
            for a in plan.activities
        ],
    )


@router.get("/micro-wins", response_model=MicroWinsResponse)
async def get_today_micro_wins(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MicroWinsResponse:
    """Last 48h of concrete wins (P3 3A-17)."""
    wins = await load_micro_wins(db, user_id=current_user.id)
    for win in wins:
        log.info(
            "today.micro_win_shown",
            user_id=str(current_user.id),
            kind=win.kind,
        )
    return MicroWinsResponse(
        wins=[
            MicroWinItem(
                kind=w.kind, label=w.label, occurred_at=w.occurred_at
            )
            for w in wins
        ]
    )
