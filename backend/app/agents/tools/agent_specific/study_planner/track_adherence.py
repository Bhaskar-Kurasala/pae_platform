"""D12 / Pass 3d §F.3 — track_adherence for study_planner.

Records what the student actually did vs. what was planned. Used both
reactively ("I finished 2 of 4 planned items") and by the proactive
nightly check (Deferral A — D16 implements the cron trigger).

Write path — asyncpg-rollback discipline applies.

Permissions: write:agent_memory
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore, MemoryWrite
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(layer="tools.study_planner.track_adherence")


class TrackAdherenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student this adherence record belongs to.")
    plan_id: str = Field(
        max_length=120,
        description="The memory_key of the plan being tracked (from commit_plan).",
    )
    actual_completion: dict[str, Any] = Field(
        description=(
            "What was actually done. Free-form dict matching the plan's "
            "activity types. Example: {'activities_completed': 2, "
            "'activities_total': 4, 'notes': 'ran out of time'}."
        )
    )
    adherence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Computed adherence 0-1 (caller computes from plan vs. actual).",
    )


class TrackAdherenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recorded: bool = True
    adherence_key: str


@tool(
    name="track_adherence",
    description=(
        "Records actual session completion vs. the committed plan. "
        "Stores adherence_score (0-1) and actual_completion dict under "
        "interaction:plan_adherence:{date} so future plans can account "
        "for real behavior patterns."
    ),
    input_schema=TrackAdherenceInput,
    output_schema=TrackAdherenceOutput,
    requires=("write:agent_memory",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def track_adherence(args: TrackAdherenceInput) -> TrackAdherenceOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError("track_adherence called without an active session.")

    date_bucket = datetime.now(UTC).strftime("%Y-%m-%d")
    adherence_key = f"interaction:plan_adherence:{date_bucket}"

    try:
        store = MemoryStore(session)
        await store.write(
            MemoryWrite(
                user_id=args.student_id,
                agent_name="study_planner",
                scope="user",
                key=adherence_key,
                value={
                    "plan_id": args.plan_id,
                    "actual": args.actual_completion,
                    "adherence_score": args.adherence_score,
                    "recorded_at": date_bucket,
                },
                # Valence reflects adherence quality: low adherence is
                # a soft negative signal (not a failure, just a pattern).
                valence=float(args.adherence_score) - 0.5,
                confidence=0.9,
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "track_adherence.write_failed",
            error=str(exc),
            student_id=str(args.student_id),
            plan_id=args.plan_id,
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "track_adherence.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        raise

    return TrackAdherenceOutput(recorded=True, adherence_key=adherence_key)


__all__ = [
    "TrackAdherenceInput",
    "TrackAdherenceOutput",
    "track_adherence",
]
