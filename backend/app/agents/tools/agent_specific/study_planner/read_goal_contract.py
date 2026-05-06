"""D12 / Pass 3d §F.3 — read_goal_contract for study_planner.

Same semantics as career_coach's read_goal_contract but registered
separately so each agent's tool registry entry is distinct. Uses the
corrected column names (weekly_hours, not weekly_hours_committed).
Filters out expired contracts (expires_at IS NULL OR > now()). D12 CP3 Part D.2.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.study_planner.read_goal_contract"
)


class SpReadGoalContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose goal contract to fetch.")


class SpGoalContractData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekly_hours: str | None = None
    target_role: str | None = None
    deadline_months: int | None = None
    motivation: str | None = None


class SpReadGoalContractOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_contract: SpGoalContractData | None = None
    has_contract: bool = False


@tool(
    name="study_planner_read_goal_contract",
    description=(
        "Returns the student's goal contract: weekly hours bucket "
        "('3-5', '6-10', '11+'), target role, and deadline in months. "
        "Used by study_planner to calibrate plan ambition to actual "
        "hours commitment."
    ),
    input_schema=SpReadGoalContractInput,
    output_schema=SpReadGoalContractOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_goal_contract(
    args: SpReadGoalContractInput,
) -> SpReadGoalContractOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "study_planner read_goal_contract called without an active session."
        )

    try:
        result = await session.execute(
            text(
                """
                SELECT weekly_hours, target_role, deadline_months, motivation
                FROM goal_contracts
                WHERE user_id = :uid
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"uid": args.student_id},
        )
        row = result.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "study_planner_read_goal_contract.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "study_planner_read_goal_contract.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return SpReadGoalContractOutput(goal_contract=None, has_contract=False)

    if row is None:
        return SpReadGoalContractOutput(goal_contract=None, has_contract=False)

    contract = SpGoalContractData(
        weekly_hours=row.weekly_hours,
        target_role=row.target_role,
        deadline_months=row.deadline_months,
        motivation=row.motivation,
    )
    return SpReadGoalContractOutput(goal_contract=contract, has_contract=True)


__all__ = [
    "SpGoalContractData",
    "SpReadGoalContractInput",
    "SpReadGoalContractOutput",
    "read_goal_contract",
]
