"""D12 / Pass 3d §F.3 — read_due_srs_cards for study_planner.

Returns SRS cards due in the next N days. Used by study_planner to
schedule review time in the plan. Read-only.

Schema fixes (D12 CP3 Phase 1): srs_cards real columns are concept_key
(not concept), next_due_at (not next_review_at), and user_id (not
student_id). The whole query was originally written against an imagined
schema; column references corrected here. The deeper question of whether
the agent's SRS scheduling logic matches what's needed is deferred to
later passes (Phase 4+).

Permissions: read:student_data
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.study_planner.read_due_srs_cards"
)


class ReadDueSrsCardsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(description="Student to fetch due cards for.")
    days_ahead: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Number of days ahead to look for due cards.",
    )


class DueSrsCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str
    due_date: str
    ease_factor: float | None


class ReadDueSrsCardsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards_due: list[DueSrsCard] = Field(default_factory=list)
    total_due: int = Field(ge=0)
    overdue_count: int = Field(ge=0)


@tool(
    name="read_due_srs_cards",
    description=(
        "Returns SRS cards due within the next N days (default 7). "
        "Includes overdue count so study_planner can prioritize review "
        "before new lessons."
    ),
    input_schema=ReadDueSrsCardsInput,
    output_schema=ReadDueSrsCardsOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_due_srs_cards(
    args: ReadDueSrsCardsInput,
) -> ReadDueSrsCardsOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_due_srs_cards called without an active session."
        )

    now = datetime.now(UTC)
    cutoff = now + timedelta(days=args.days_ahead)

    try:
        result = await session.execute(
            text(
                """
                SELECT
                    concept_key AS concept,
                    next_due_at::text AS due_date,
                    ease_factor,
                    (next_due_at < now()) AS is_overdue
                FROM srs_cards
                WHERE user_id = :uid
                  AND next_due_at <= :cutoff
                ORDER BY next_due_at ASC
                LIMIT 100
                """
            ),
            {"uid": args.student_id, "cutoff": cutoff},
        )
        rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_due_srs_cards.query_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_due_srs_cards.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return ReadDueSrsCardsOutput(cards_due=[], total_due=0, overdue_count=0)

    cards: list[DueSrsCard] = []
    overdue = 0
    for row in rows:
        cards.append(
            DueSrsCard(
                concept=row.concept,
                due_date=row.due_date,
                ease_factor=float(row.ease_factor) if row.ease_factor is not None else None,
            )
        )
        if row.is_overdue:
            overdue += 1

    return ReadDueSrsCardsOutput(
        cards_due=cards,
        total_due=len(cards),
        overdue_count=overdue,
    )


__all__ = [
    "DueSrsCard",
    "ReadDueSrsCardsInput",
    "ReadDueSrsCardsOutput",
    "read_due_srs_cards",
]
