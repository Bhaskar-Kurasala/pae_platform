"""Intent clarification + follow-up pill endpoints (P3 3A-4).

Thin route surface — pure helpers do all the work. FE calls
`/clarify/check` before sending the student's message to the tutor;
if `show_pills=true`, FE renders the pill row instead of streaming
the response. `/clarify/followups` is called after every
substantive reply to get the next-move pills.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.schemas.clarification import (
    ClarifyCheckRequest,
    ClarifyCheckResponse,
    FollowupRequest,
    FollowupResponse,
    PillItem,
)
from app.services.clarification_service import (
    generate_followups,
    should_clarify,
)

log = structlog.get_logger()

router = APIRouter(prefix="/clarify", tags=["clarification"])


async def _load_socratic_level(
    db: AsyncSession, user_id: object
) -> int:
    result = await db.execute(
        select(UserPreferences.socratic_level).where(
            UserPreferences.user_id == user_id
        )
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else 2


@router.post("/check", response_model=ClarifyCheckResponse)
async def check_clarification(
    payload: ClarifyCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClarifyCheckResponse:
    """Decide whether to show clarify pills for a student message."""
    socratic_level = await _load_socratic_level(db, current_user.id)
    decision = should_clarify(
        payload.message, socratic_level=socratic_level
    )
    if decision.show_pills:
        log.info(
            "tutor.clarification_shown",
            user_id=str(current_user.id),
            reason=decision.reason,
        )
    return ClarifyCheckResponse(
        show_pills=decision.show_pills,
        reason=decision.reason,
        pills=[
            PillItem(key=p.key, label=p.label) for p in decision.pills
        ],
    )


@router.post("/followups", response_model=FollowupResponse)
async def followup_pills(
    payload: FollowupRequest,
    current_user: User = Depends(get_current_user),
) -> FollowupResponse:
    """Return 0-3 contextual follow-up pills for a tutor reply."""
    pills = generate_followups(payload.reply)
    return FollowupResponse(
        pills=[PillItem(key=p.key, label=p.label) for p in pills]
    )
