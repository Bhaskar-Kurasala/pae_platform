from datetime import UTC, date, datetime, timedelta, timezone

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reflection import Reflection
from app.models.user import User
from app.schemas.reflection import ReflectionCreate

log = structlog.get_logger()


def _today_utc() -> date:
    return datetime.now(UTC).date()


# P3 3A-12: evening threshold. Ticket specifies "only after 6pm local".
_DAY_END_HOUR = 18


def is_day_end_window(
    now: datetime, *, tz_offset_hours: int, hour_floor: int = _DAY_END_HOUR
) -> bool:
    """True if `now` is past 6pm in the caller's local timezone.

    The frontend passes the student's timezone offset; we do the clock
    math here so the gate lives next to the rest of the reflection
    logic. If the frontend omits an offset (e.g., a server-side call),
    `tz_offset_hours=0` is treated as UTC.
    """
    local_tz = timezone(timedelta(hours=tz_offset_hours))
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local = now.astimezone(local_tz)
    return local.hour >= hour_floor


class ReflectionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_date(
        self, user: User, on_date: date
    ) -> Reflection | None:
        result = await self.db.execute(
            select(Reflection).where(
                Reflection.user_id == user.id,
                Reflection.reflection_date == on_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_today(self, user: User) -> Reflection | None:
        return await self.get_for_date(user, _today_utc())

    async def list_recent(
        self, user: User, limit: int = 30
    ) -> list[Reflection]:
        result = await self.db.execute(
            select(Reflection)
            .where(Reflection.user_id == user.id)
            .order_by(desc(Reflection.reflection_date))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def upsert(
        self, user: User, payload: ReflectionCreate
    ) -> tuple[Reflection, bool]:
        on_date = payload.reflection_date or _today_utc()
        existing = await self.get_for_date(user, on_date)
        if existing is not None:
            existing.mood = payload.mood
            existing.note = payload.note
            existing.kind = payload.kind
            await self.db.flush()
            await self.db.refresh(existing)
            log.info(
                "reflection.answered",
                user_id=str(user.id),
                mood=payload.mood,
                reflection_date=on_date.isoformat(),
                kind=payload.kind,
                updated=True,
            )
            if payload.kind == "day_end":
                log.info(
                    "today.day_end_answered",
                    user_id=str(user.id),
                    mood=payload.mood,
                )
            return existing, False

        reflection = Reflection(
            user_id=user.id,
            reflection_date=on_date,
            mood=payload.mood,
            note=payload.note,
            kind=payload.kind,
        )
        self.db.add(reflection)
        await self.db.flush()
        await self.db.refresh(reflection)
        log.info(
            "reflection.answered",
            user_id=str(user.id),
            mood=payload.mood,
            reflection_date=on_date.isoformat(),
            kind=payload.kind,
            updated=False,
        )
        if payload.kind == "day_end":
            log.info(
                "today.day_end_answered",
                user_id=str(user.id),
                mood=payload.mood,
            )
        return reflection, True
