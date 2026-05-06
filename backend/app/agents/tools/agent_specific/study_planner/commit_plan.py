"""D12 / Pass 3d §F.3 — commit_plan for study_planner.

Persists a weekly or session plan to agent_memory so track_adherence
can compare actual vs. planned later. Write path — asyncpg-rollback
discipline applies.

Permissions: write:agent_memory
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore, MemoryWrite
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(layer="tools.study_planner.commit_plan")


class CommitPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student this plan belongs to.")
    plan_type: Literal["weekly", "session"] = Field(
        description="Plan type — weekly or single session."
    )
    plan_data: dict[str, Any] = Field(
        description="The plan payload (mode-specific fields from StudyPlannerOutput)."
    )
    idempotency_key: str = Field(
        max_length=80,
        description=(
            "Unique key for this plan (e.g. 'weekly:2026-W18' or "
            "'session:2026-05-06'). Prevents duplicate commits."
        ),
    )


class CommitPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(description="Memory key under which the plan was stored.")
    was_new: bool = Field(
        description="True if written fresh; False if idempotency_key matched existing."
    )


@tool(
    name="commit_plan",
    description=(
        "Persists a weekly or session plan to agent_memory for adherence tracking. "
        "Idempotent: if the same idempotency_key was already committed, returns "
        "was_new=False without overwriting. Called by study_planner after finalizing "
        "the plan so track_adherence has a reference to compare against."
    ),
    input_schema=CommitPlanInput,
    output_schema=CommitPlanOutput,
    requires=("write:agent_memory",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def commit_plan(args: CommitPlanInput) -> CommitPlanOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError("commit_plan called without an active session.")

    memory_key = f"plan:{args.plan_type}:{args.idempotency_key}"

    try:
        store = MemoryStore(session)

        existing = await store.recall(
            memory_key,
            user_id=args.student_id,
            agent_name="study_planner",
            scope="user",
            k=1,
            mode="structured",
        )
        if existing:
            return CommitPlanOutput(plan_id=memory_key, was_new=False)

        await store.write(
            MemoryWrite(
                user_id=args.student_id,
                agent_name="study_planner",
                scope="user",
                key=memory_key,
                value={
                    "plan_type": args.plan_type,
                    "idempotency_key": args.idempotency_key,
                    "plan": args.plan_data,
                },
                valence=0.0,
                confidence=1.0,
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "commit_plan.write_failed",
            error=str(exc),
            student_id=str(args.student_id),
            memory_key=memory_key,
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "commit_plan.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        raise

    return CommitPlanOutput(plan_id=memory_key, was_new=True)


__all__ = [
    "CommitPlanInput",
    "CommitPlanOutput",
    "commit_plan",
]
