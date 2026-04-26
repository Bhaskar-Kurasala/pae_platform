"""Readiness workspace event ingestion service.

Best-effort telemetry for the Job Readiness workspace. The frontend POSTs
clicks/views in batches every few seconds; we write them with a generic
(view + event + payload) shape so adding a new event NEVER requires a
schema migration or backend deploy.

Partial-accept on batches: malformed entries are skipped individually so
one bad row never sinks the rest of the batch.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.readiness_workspace_event import ReadinessWorkspaceEvent

log = structlog.get_logger()


# Hard-validated: any unknown view is rejected. These map to the workspace
# subnav surfaces the frontend renders.
VIEW_KINDS: set[str] = {
    "overview",
    "resume",
    "jd",
    "interview",
    "proof",
    "kit",
    "global",
}

# Soft-validated: unknown events are accepted but logged so we can spot
# typos without blocking the frontend from shipping new event names.
EVENT_KINDS: set[str] = {
    "view_opened",
    "subnav_clicked",
    "cta_clicked",
    "kit_build_started",
    "kit_downloaded",
    "jd_preset_selected",
    "autopsy_started",
    "external_link_clicked",
    "diagnostic_started",
    "diagnostic_finalized",
}


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def record_event(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    view: str,
    event: str,
    payload: dict[str, Any] | None = None,
    session_id: uuid.UUID | str | None = None,
    occurred_at: datetime | None = None,
) -> ReadinessWorkspaceEvent:
    """Insert a single workspace event.

    Validates ``view`` against ``VIEW_KINDS`` (raises ``ValueError`` on
    miss). ``event`` is soft-validated — unknown values are accepted but
    surface a warning log so we can catch frontend typos.
    """
    if view not in VIEW_KINDS:
        raise ValueError(
            f"unknown view {view!r}; expected one of {sorted(VIEW_KINDS)}"
        )
    if event not in EVENT_KINDS:
        # NB: `event` is reserved by structlog (it's the message key), so
        # we surface the user's event-string as `event_kind` here and in
        # every other warning in this module. Same hard rule for `level`,
        # `timestamp`, etc. — see structlog docs.
        log.warning(
            "readiness_workspace_event.unknown_event",
            event_kind=event,
            view=view,
            user_id=str(user_id),
        )

    row = ReadinessWorkspaceEvent(
        user_id=user_id,
        view=view,
        event=event,
        payload=payload,
        session_id=_coerce_uuid(session_id),
        occurred_at=occurred_at or _now_utc(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def record_events_batch(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    events: Iterable[dict[str, Any]],
) -> int:
    """Bulk-insert events with per-row error isolation.

    Returns the count of successful inserts. Bad entries (missing required
    keys, unknown view, malformed UUID/datetime) are skipped with a
    warning — partial accept is the right semantics here because this is
    best-effort telemetry, not a transactional write.
    """
    rows: list[ReadinessWorkspaceEvent] = []
    skipped = 0
    for raw in events:
        try:
            view = raw["view"]
            event = raw["event"]
        except (KeyError, TypeError):
            skipped += 1
            log.warning(
                "readiness_workspace_event.missing_keys",
                user_id=str(user_id),
                raw=raw,
            )
            continue

        if not isinstance(view, str) or view not in VIEW_KINDS:
            skipped += 1
            log.warning(
                "readiness_workspace_event.invalid_view",
                user_id=str(user_id),
                view=view,
            )
            continue
        if not isinstance(event, str) or not event:
            skipped += 1
            log.warning(
                "readiness_workspace_event.invalid_event",
                user_id=str(user_id),
                event_kind=event,
            )
            continue
        if event not in EVENT_KINDS:
            log.warning(
                "readiness_workspace_event.unknown_event",
                event_kind=event,
                view=view,
                user_id=str(user_id),
            )

        try:
            session_id = _coerce_uuid(raw.get("session_id"))
        except (ValueError, TypeError):
            skipped += 1
            log.warning(
                "readiness_workspace_event.invalid_session_id",
                user_id=str(user_id),
                session_id=raw.get("session_id"),
            )
            continue

        occurred_at = raw.get("occurred_at") or _now_utc()
        if not isinstance(occurred_at, datetime):
            skipped += 1
            log.warning(
                "readiness_workspace_event.invalid_occurred_at",
                user_id=str(user_id),
                occurred_at=occurred_at,
            )
            continue

        payload = raw.get("payload")
        if payload is not None and not isinstance(payload, dict):
            skipped += 1
            log.warning(
                "readiness_workspace_event.invalid_payload",
                user_id=str(user_id),
                payload_type=type(payload).__name__,
            )
            continue

        rows.append(
            ReadinessWorkspaceEvent(
                user_id=user_id,
                view=view,
                event=event,
                payload=payload,
                session_id=session_id,
                occurred_at=occurred_at,
            )
        )

    if not rows:
        if skipped:
            log.info(
                "readiness_workspace_event.batch_all_skipped",
                user_id=str(user_id),
                skipped=skipped,
            )
        return 0

    db.add_all(rows)
    await db.commit()
    log.info(
        "readiness_workspace_event.batch_recorded",
        user_id=str(user_id),
        recorded=len(rows),
        skipped=skipped,
    )
    return len(rows)


async def list_recent_events(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 50,
    view: str | None = None,
) -> list[ReadinessWorkspaceEvent]:
    """Return the user's events newest-first, optionally filtered by view."""
    q = (
        select(ReadinessWorkspaceEvent)
        .where(ReadinessWorkspaceEvent.user_id == user_id)
        .order_by(desc(ReadinessWorkspaceEvent.occurred_at))
        .limit(limit)
    )
    if view is not None:
        q = q.where(ReadinessWorkspaceEvent.view == view)
    result = await db.execute(q)
    return list(result.scalars().all())


async def event_summary(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    since_days: int = 7,
) -> dict[str, Any]:
    """Aggregate the user's last ``since_days`` of events for analytics.

    Returns ``{total, by_view, by_event, last_event_at}``. Counter math is
    done in Python (rather than two GROUP BY queries) because the working
    set is small (capped by the index window) and a single round-trip is
    cheaper than two.
    """
    since = _now_utc() - timedelta(days=since_days)
    q = (
        select(
            ReadinessWorkspaceEvent.view,
            ReadinessWorkspaceEvent.event,
            ReadinessWorkspaceEvent.occurred_at,
        )
        .where(
            ReadinessWorkspaceEvent.user_id == user_id,
            ReadinessWorkspaceEvent.occurred_at >= since,
        )
        .order_by(desc(ReadinessWorkspaceEvent.occurred_at))
    )
    result = await db.execute(q)
    rows = result.all()

    by_view: Counter[str] = Counter()
    by_event: Counter[str] = Counter()
    last_event_at: datetime | None = None
    for view, event, occurred_at in rows:
        by_view[view] += 1
        by_event[event] += 1
        if last_event_at is None or occurred_at > last_event_at:
            last_event_at = occurred_at

    # Fall back to a separate MAX query if the window cut off the latest.
    if last_event_at is None:
        max_q = select(func.max(ReadinessWorkspaceEvent.occurred_at)).where(
            ReadinessWorkspaceEvent.user_id == user_id
        )
        last_event_at = (await db.execute(max_q)).scalar()

    return {
        "total": len(rows),
        "by_view": dict(by_view),
        "by_event": dict(by_event),
        "last_event_at": last_event_at,
    }
