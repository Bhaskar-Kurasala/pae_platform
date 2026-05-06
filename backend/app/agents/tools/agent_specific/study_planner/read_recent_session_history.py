"""D12 / Pass 3d §F.3 — read_recent_session_history for study_planner.

Returns what the student actually did in their study sessions over the
last N days — lessons watched, exercises submitted, review done. Used
by study_planner for adherence assessment and plan calibration.

Reads from agent_memory under plan:session:* keys (plans the
study_planner itself committed) and student_progress.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.study_planner.read_recent_session_history"
)


class ReadRecentSessionHistoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose session history to fetch.")
    days: int = Field(
        default=14,
        ge=1,
        le=30,
        description="How many days back to look.",
    )


class SessionHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    summary: str
    adherence_score: float | None


class ReadRecentSessionHistoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionHistoryEntry] = Field(default_factory=list)
    avg_adherence: float | None = None
    days_with_activity: int = Field(ge=0)


@tool(
    name="read_recent_session_history",
    description=(
        "Returns a student's study activity for the last N days (default 14). "
        "Reads committed session plans and adherence outcomes from agent_memory. "
        "Used by study_planner to calibrate new plans against actual behavior."
    ),
    input_schema=ReadRecentSessionHistoryInput,
    output_schema=ReadRecentSessionHistoryOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_recent_session_history(
    args: ReadRecentSessionHistoryInput,
) -> ReadRecentSessionHistoryOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_recent_session_history called without an active session."
        )

    try:
        store = MemoryStore(session)
        rows = await store.recall(
            "plan:session",
            user_id=args.student_id,
            agent_name="study_planner",
            scope="user",
            k=args.days * 2,
            mode="structured",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_recent_session_history.recall_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_recent_session_history.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadRecentSessionHistoryOutput(
            sessions=[], avg_adherence=None, days_with_activity=0
        )

    cutoff = datetime.now(UTC) - timedelta(days=args.days)
    entries: list[SessionHistoryEntry] = []
    scores: list[float] = []

    for row in rows:
        if not row.key.startswith("plan:session"):
            continue
        if row.created_at < cutoff:
            continue
        val = row.value if isinstance(row.value, dict) else {}
        adh = val.get("adherence_score")
        entries.append(
            SessionHistoryEntry(
                date=row.created_at.strftime("%Y-%m-%d"),
                summary=str(val.get("summary", "session logged"))[:200],
                adherence_score=float(adh) if adh is not None else None,
            )
        )
        if adh is not None:
            scores.append(float(adh))

    avg = sum(scores) / len(scores) if scores else None
    return ReadRecentSessionHistoryOutput(
        sessions=entries,
        avg_adherence=avg,
        days_with_activity=len(entries),
    )


__all__ = [
    "ReadRecentSessionHistoryInput",
    "ReadRecentSessionHistoryOutput",
    "SessionHistoryEntry",
    "read_recent_session_history",
]
