"""D12 / Pass 3d §E.2 — read_goal_contract for career_coach.

Reads the student's active goal_contract using the corrected column
names from migration 0060 (weekly_hours: str, target_role: str,
deadline_months: int). Filters out expired contracts so that only the
most-recent active (unexpired) row is returned. D12 CP3 Part D.1.

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
    layer="tools.career_coach.read_goal_contract"
)


class ReadGoalContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student whose goal contract to fetch.")


class GoalContractData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekly_hours: str | None = None
    target_role: str | None = None
    deadline_months: int | None = None
    motivation: str | None = None
    success_statement: str | None = None


class ReadGoalContractOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_contract: GoalContractData | None = None
    has_contract: bool = False


@tool(
    name="read_goal_contract",
    description=(
        "Returns the student's active goal contract: weekly hours "
        "commitment (bucket string like '3-5', '6-10', '11+'), target "
        "role, deadline in months, motivation, and success statement. "
        "Returns has_contract=False when no contract exists."
    ),
    input_schema=ReadGoalContractInput,
    output_schema=ReadGoalContractOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_goal_contract(
    args: ReadGoalContractInput,
) -> ReadGoalContractOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_goal_contract called without an active session."
        )

    try:
        result = await session.execute(
            text(
                """
                SELECT weekly_hours, target_role, deadline_months,
                       motivation, success_statement
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
            "read_goal_contract.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_goal_contract.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadGoalContractOutput(goal_contract=None, has_contract=False)

    if row is None:
        return ReadGoalContractOutput(goal_contract=None, has_contract=False)

    contract = GoalContractData(
        weekly_hours=row.weekly_hours,
        target_role=row.target_role,
        deadline_months=row.deadline_months,
        motivation=row.motivation,
        success_statement=row.success_statement,
    )
    return ReadGoalContractOutput(goal_contract=contract, has_contract=True)


__all__ = [
    "GoalContractData",
    "ReadGoalContractInput",
    "ReadGoalContractOutput",
    "read_goal_contract",
]
