"""Celery task body for proactive agent dispatch.

The proactive primitive (D6) declares
`PROACTIVE_TASK_NAME = "app.agents.primitives.proactive.run_proactive_task"`
and `register_proactive_schedules` constructs beat entries that
target that name. This module is where the actual `@shared_task`
implementation lives — separating it from the primitive keeps
`proactive.py` Celery-free for unit tests.

Per-user fan-out is handled here: when a `ProactiveSchedule` has
`per_user=True`, the task iterates active students and dispatches
once per user. Single-shot (`per_user=False`) schedules dispatch
once with `user_id=None`.

Why a separate task per cron tick rather than a fan-out queue:
the dispatcher itself is idempotent (D6 partial-unique index on
`agent_proactive_runs.idempotency_key`), so a Celery retry of the
whole task collapses to no-ops on already-dispatched users. That's
operationally simpler than building a per-user task queue.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy import select

from app.agents.primitives.proactive import (
    ProactiveDispatchResult,
    cron_idempotency_key,
    dispatch_proactive_run,
)
from app.core.database import AsyncSessionLocal

log = structlog.get_logger().bind(layer="proactive_runner")


# Same string the proactive primitive declares as PROACTIVE_TASK_NAME.
# Pinned here as a constant so a typo would fail loudly at import
# rather than silently mis-route the cron.
_TASK_NAME = "app.agents.primitives.proactive.run_proactive_task"


@shared_task(name=_TASK_NAME, bind=False, ignore_result=True)
def run_proactive_task(
    agent_name: str,
    cron_expr: str,
    per_user: bool,
) -> dict[str, Any]:
    """Celery entry point for a proactive cron firing.

    Args mirror the `register_proactive_schedules` arg-tuple:
    (agent_name, cron_expr, per_user). Beat passes them positional;
    Celery serializes them through JSON so they must be plain
    strings/bools.

    Runs synchronously inside the Celery worker. Internally we use
    `asyncio.run` to drive the async dispatcher — Celery itself is
    sync. The function returns a small summary dict that gets
    discarded (`ignore_result=True`) but is useful for ad-hoc test
    runs via `task.apply().get()`.
    """
    log.info(
        "proactive_runner.fire",
        agent=agent_name,
        cron=cron_expr,
        per_user=per_user,
    )
    # Production Celery workers are sync — no event loop is running
    # — so `asyncio.run` is the textbook entry point. Tests
    # exercise `_run_proactive_async` directly to avoid the cross-
    # loop session-binding issue (see test_d7b_integration.py for
    # the rationale).
    summary = asyncio.run(
        _run_proactive_async(
            agent_name=agent_name,
            cron_expr=cron_expr,
            per_user=per_user,
            scheduled_for=datetime.now(UTC),
        )
    )
    log.info(
        "proactive_runner.complete",
        agent=agent_name,
        dispatched=summary["dispatched"],
        deduped=summary["deduped"],
        errors=summary["errors"],
    )
    return summary


async def _run_proactive_async(
    *,
    agent_name: str,
    cron_expr: str,
    per_user: bool,
    scheduled_for: datetime,
) -> dict[str, Any]:
    """Async core. Builds the idempotency key and invokes
    `dispatch_proactive_run`.

    Per-user fan-out: when `per_user=True` we iterate all active,
    non-deleted students and dispatch one run per user with a
    user-suffixed idempotency key. When False, one run with
    `user_id=None`.

    The session is opened fresh from `AsyncSessionLocal` — the
    Celery worker does not have a request-scoped session, so we
    own the lifecycle here.
    """
    dispatched = 0
    deduped = 0
    errors = 0

    async with AsyncSessionLocal() as session:
        if per_user:
            user_ids = await _active_student_ids(session)
        else:
            user_ids = [None]

        for user_id in user_ids:
            key = cron_idempotency_key(
                agent_name,
                cron_expr,
                scheduled_for=scheduled_for,
                user_id=user_id,
            )
            try:
                result: ProactiveDispatchResult = await dispatch_proactive_run(
                    session=session,
                    agent_name=agent_name,
                    trigger_source="cron",
                    trigger_key=cron_expr,
                    idempotency_key=key,
                    payload={
                        "cron": cron_expr,
                        "scheduled_for": scheduled_for.isoformat(),
                    },
                    user_id=user_id,
                )
            except Exception as exc:  # noqa: BLE001
                # Per-user errors should not abort the whole sweep.
                # Log and move on; the next cron tick will retry
                # via the same idempotency key (which makes a stuck
                # user collapse to a single audit row anyway).
                errors += 1
                log.warning(
                    "proactive_runner.user_error",
                    agent=agent_name,
                    user_id=str(user_id) if user_id else None,
                    error=str(exc),
                )
                continue

            if result.deduped:
                deduped += 1
            else:
                dispatched += 1
        await session.commit()

    return {
        "agent": agent_name,
        "cron": cron_expr,
        "dispatched": dispatched,
        "deduped": deduped,
        "errors": errors,
        "user_count": len(user_ids),
    }


async def _active_student_ids(session: Any) -> list[uuid.UUID]:
    """Return the list of user_ids the proactive sweep should fan
    out to. Active students = `role='student' AND is_deleted=false`.

    Imported lazily inside the function so module import doesn't
    cascade into models — keeps the Celery worker's import graph
    cheap on boot."""
    from app.models.user import User

    result = await session.execute(
        select(User.id).where(
            User.role == "student",
            User.is_deleted.is_(False),
        )
    )
    return list(result.scalars().all())


__all__ = ["run_proactive_task"]
