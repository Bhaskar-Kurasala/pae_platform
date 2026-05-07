"""D14c / Pass 3c E9 — read_rubric_for_capstone.

Returns the rubric stored on `exercises.rubric` for a given exercise,
serialized to a JSON-pretty string the prompt can ingest verbatim.

D-1 spec-vs-schema reconciliation: Pass 3c E9 spec named this
`read_rubric_for_course` against a `course_content` table that doesn't
exist. Actual schema stores rubrics on `exercises.rubric` (JSON,
nullable), per-capstone exercise. Tool renamed at D14c CP1.

D-E rubric-grounding contract: when `exercises.rubric` is NULL, the
tool returns `rubric_text=None`. The agent's run() converts this to
the literal `RUBRIC_UNAVAILABLE` marker in the user_block, which the
prompt's hard constraints map to the structured-refusal path.

Permissions: read:student_data — the rubric belongs to the course
content authored by instructors; not personally identifying, but we
keep the same permission gate as other content reads.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.project_evaluator.read_rubric_for_capstone"
)


class ReadRubricForCapstoneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: uuid.UUID = Field(
        description=(
            "exercises.id — the capstone whose rubric to fetch. "
            "Typically derived by the agent from a submission's "
            "exercise_id FK."
        ),
    )


class ReadRubricForCapstoneOutput(BaseModel):
    """Rubric projection for project_evaluator's user_block.

    `found=False` when no exercises row exists for the given id. In
    that case other fields are None / False / empty.

    `rubric_json` is the raw JSON value as stored. `rubric_text` is
    `json.dumps(rubric_json, indent=2)` when present, None otherwise
    — the agent injects this verbatim into the prompt's `## Rubric`
    section. None triggers the RUBRIC_UNAVAILABLE marker (D-E).

    `is_capstone` is exposed for defensive cross-checking in the
    agent (the agent should already have early-exited via
    read_capstone_submission_content if is_capstone=False; this is a
    second-line defense).
    """

    model_config = ConfigDict(extra="forbid")

    found: bool = Field(
        description=(
            "True iff an exercises row was found for the given id."
        ),
    )

    rubric_json: dict[str, Any] | None = None
    rubric_text: str | None = Field(
        default=None,
        description=(
            "json.dumps(rubric_json, indent=2) when the rubric is "
            "non-NULL; None otherwise. None triggers D-E "
            "RUBRIC_UNAVAILABLE in the agent's user_block."
        ),
    )
    is_capstone: bool = False
    exercise_title: str | None = None


@tool(
    name="read_rubric_for_capstone",
    description=(
        "Returns the rubric stored on exercises.rubric for a given "
        "capstone exercise. Output includes a JSON-pretty rubric_text "
        "field the agent injects into the prompt's user_block. NULL "
        "rubric → rubric_text=None → triggers RUBRIC_UNAVAILABLE refusal "
        "path in the agent."
    ),
    input_schema=ReadRubricForCapstoneInput,
    output_schema=ReadRubricForCapstoneOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def read_rubric_for_capstone(
    args: ReadRubricForCapstoneInput,
) -> ReadRubricForCapstoneOutput:
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_rubric_for_capstone called without an active session."
        )

    try:
        result = await session.execute(
            sql_text(
                """
                SELECT
                    e.rubric,
                    e.is_capstone,
                    e.title AS exercise_title
                FROM exercises e
                WHERE e.id = :exercise_id
                """
            ),
            {"exercise_id": args.exercise_id},
        )
        row = result.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_rubric_for_capstone.query_failed",
            error=str(exc),
            exercise_id=str(args.exercise_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_rubric_for_capstone.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                exercise_id=str(args.exercise_id),
            )
        return ReadRubricForCapstoneOutput(found=False)

    if row is None:
        return ReadRubricForCapstoneOutput(found=False)

    rubric_json = row.rubric  # SQLAlchemy returns Python dict for JSON column
    rubric_text: str | None = None
    if rubric_json is not None:
        # Pretty-print so the LLM gets readable structure. The prompt
        # treats this string as the canonical rubric_text. We pass
        # ensure_ascii=False so non-ASCII rubric content (e.g.,
        # international characters in dimension descriptions) renders
        # natively rather than as \u escapes.
        try:
            rubric_text = json.dumps(rubric_json, indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            # Defensive: if the stored JSON contains non-serializable
            # content (shouldn't happen in normal flow), log and treat
            # as unavailable.
            log.warning(
                "read_rubric_for_capstone.serialize_failed",
                error=str(exc),
                exercise_id=str(args.exercise_id),
            )
            rubric_text = None

    return ReadRubricForCapstoneOutput(
        found=True,
        rubric_json=rubric_json if isinstance(rubric_json, dict) else None,
        rubric_text=rubric_text,
        is_capstone=bool(row.is_capstone),
        exercise_title=row.exercise_title,
    )


__all__ = [
    "ReadRubricForCapstoneInput",
    "ReadRubricForCapstoneOutput",
    "read_rubric_for_capstone",
]
