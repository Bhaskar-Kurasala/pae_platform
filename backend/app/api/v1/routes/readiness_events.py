"""Readiness workspace event ingestion API.

POST /api/v1/readiness/events           — record one event or a batch
GET  /api/v1/readiness/events           — recent events for the user
GET  /api/v1/readiness/events/summary   — aggregated counts for analytics
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.readiness_events import (
    RecordEventBatchRequest,
    RecordEventBatchResponse,
    WorkspaceEventOut,
    WorkspaceEventSummaryResponse,
)
from app.services.readiness_workspace_event_service import (
    event_summary,
    list_recent_events,
    record_events_batch,
)

log = structlog.get_logger()

router = APIRouter(
    prefix="/readiness/events", tags=["readiness-workspace-events"]
)


@router.post("", response_model=RecordEventBatchResponse)
async def post_events(
    payload: RecordEventBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecordEventBatchResponse:
    """Record one event or a batch. Partial accept by design."""
    submitted = len(payload.events)
    raw_events = [e.model_dump() for e in payload.events]
    recorded = await record_events_batch(
        db, user_id=current_user.id, events=raw_events
    )
    skipped = max(0, submitted - recorded)
    log.info(
        "readiness_workspace_event.posted",
        user_id=str(current_user.id),
        submitted=submitted,
        recorded=recorded,
        skipped=skipped,
    )
    return RecordEventBatchResponse(recorded=recorded, skipped=skipped)


@router.get("", response_model=list[WorkspaceEventOut])
async def get_events(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    view: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WorkspaceEventOut]:
    """Newest-first list of the current user's workspace events."""
    rows = await list_recent_events(
        db, user_id=current_user.id, limit=limit, view=view
    )
    return [WorkspaceEventOut.model_validate(r) for r in rows]


@router.get("/summary", response_model=WorkspaceEventSummaryResponse)
async def get_event_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    since_days: int = Query(default=7, ge=1, le=90),
) -> WorkspaceEventSummaryResponse:
    """Aggregate the user's last ``since_days`` of events."""
    summary = await event_summary(
        db, user_id=current_user.id, since_days=since_days
    )
    return WorkspaceEventSummaryResponse(
        total=summary["total"],
        by_view=summary["by_view"],
        by_event=summary["by_event"],
        last_event_at=summary["last_event_at"],
        since_days=since_days,
        generated_at=datetime.now(UTC),
    )
