"""D14c / Pass 3c E9 — read_capstone_submission_content.

Returns the full content of a single capstone submission joined with
its parent exercise, so project_evaluator has everything it needs for
rubric-grounded evaluation: code, github_pr_url, self_explanation,
exercise metadata, and the load-bearing `is_capstone` flag.

D-3 mapping (locked at CP1): the agent's `project_submission_id`
input field maps to `exercise_submissions.id`. The submission's
`exercise_id` FK joins `exercises`; we project the joined row so the
agent's run() can route on `is_capstone` via D-4 early-exit.

D-4 dual-rail contract: the tool DOES NOT filter on `is_capstone` at
the SQL level — it returns the joined row regardless and exposes the
flag at the top level of the output. The agent owns the routing
decision (graceful refusal vs continue evaluation). Filtering at SQL
would silently drop non-capstone submissions and yield a `None` that
looks indistinguishable from "submission not found", collapsing two
distinct failure modes into one.

Permissions: read:student_data
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.project_evaluator.read_capstone_submission_content"
)


class ReadCapstoneSubmissionContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID = Field(
        description=(
            "exercise_submissions.id — the submission to fetch. The "
            "tool resolves the joined exercise row to expose is_capstone "
            "for D-4 dual-rail routing in the agent."
        ),
    )
    # D17b/ITEM 2.A — entitlement gate. The tool's previous shape
    # (submission_id only) allowed cross-student leak: an agent invoked
    # with a submission_id from another student would return that
    # submission's content. Caller passes ctx.user_id; SQL gates
    # `AND es.student_id = :student_id`. Mismatched ownership returns
    # found=False (single error mode — does NOT distinguish "not found"
    # from "not yours" so the caller can't probe existence).
    student_id: uuid.UUID = Field(
        description=(
            "The student the agent is acting on behalf of (typically "
            "ctx.user_id). The tool returns found=False if the submission "
            "is not owned by this student — closes the cross-student leak "
            "vector flagged in d12-d14c-read-tool-entitlement-leakage-audit "
            "(MEDIUM finding, D17b/ITEM 2.A)."
        ),
    )


class ReadCapstoneSubmissionContentOutput(BaseModel):
    """Joined submission + exercise projection.

    `found=False` when no row exists for the given submission_id;
    other fields are None in that case. The agent treats `found=False`
    the same as a non-capstone submission for routing purposes
    (architectural-contract violation; refusal path).

    `is_capstone` is the load-bearing D-4 routing flag — the agent
    early-exits to the NON_CAPSTONE_SUBMISSION refusal path when it's
    False (or when found=False).
    """

    model_config = ConfigDict(extra="forbid")

    found: bool = Field(
        description=(
            "True iff a submission row was found for the given id."
        ),
    )

    submission_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    exercise_id: uuid.UUID | None = None

    code: str | None = None
    github_pr_url: str | None = None
    self_explanation: str | None = None
    feedback: str | None = None
    ai_feedback: dict[str, Any] | None = None
    score: int | None = None
    status: str | None = None

    exercise_title: str | None = None
    exercise_description: str | None = None
    is_capstone: bool = Field(
        default=False,
        description=(
            "Load-bearing D-4 routing flag — True iff the joined "
            "exercise has is_capstone=TRUE. Agent's run() routes to "
            "NON_CAPSTONE_SUBMISSION refusal when False."
        ),
    )


@tool(
    name="read_capstone_submission_content",
    description=(
        "Returns the full content of a capstone submission joined "
        "with its parent exercise: code, github_pr_url, "
        "self_explanation, exercise metadata, and is_capstone flag. "
        "The tool does NOT filter on is_capstone — the agent owns "
        "the D-4 routing decision."
    ),
    input_schema=ReadCapstoneSubmissionContentInput,
    output_schema=ReadCapstoneSubmissionContentOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def read_capstone_submission_content(
    args: ReadCapstoneSubmissionContentInput,
) -> ReadCapstoneSubmissionContentOutput:
    """Read a single submission joined with its exercise via raw SQL."""
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "read_capstone_submission_content called without an active "
            "session. The tool body relies on the contextvar set by "
            "call_agent."
        )

    try:
        result = await session.execute(
            sql_text(
                """
                SELECT
                    es.id::text AS submission_id,
                    es.student_id::text AS student_id,
                    es.exercise_id::text AS exercise_id,
                    es.code,
                    es.github_pr_url,
                    es.self_explanation,
                    es.feedback,
                    es.ai_feedback,
                    es.score,
                    es.status,
                    e.title AS exercise_title,
                    e.description AS exercise_description,
                    e.is_capstone
                FROM exercise_submissions es
                JOIN exercises e ON es.exercise_id = e.id
                WHERE es.id = :submission_id
                  AND es.student_id = :student_id
                """
            ),
            {
                "submission_id": args.submission_id,
                "student_id": args.student_id,
            },
        )
        row = result.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "read_capstone_submission_content.query_failed",
            error=str(exc),
            submission_id=str(args.submission_id),
        )
        # asyncpg-rollback discipline per
        # docs/followups/asyncpg-rollback-discipline.md
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "read_capstone_submission_content.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                submission_id=str(args.submission_id),
            )
        return ReadCapstoneSubmissionContentOutput(found=False)

    if row is None:
        return ReadCapstoneSubmissionContentOutput(found=False)

    return ReadCapstoneSubmissionContentOutput(
        found=True,
        submission_id=uuid.UUID(row.submission_id),
        student_id=uuid.UUID(row.student_id),
        exercise_id=uuid.UUID(row.exercise_id),
        code=row.code,
        github_pr_url=row.github_pr_url,
        self_explanation=row.self_explanation,
        feedback=row.feedback,
        ai_feedback=row.ai_feedback,
        score=row.score,
        status=row.status,
        exercise_title=row.exercise_title,
        exercise_description=row.exercise_description,
        is_capstone=bool(row.is_capstone),
    )


__all__ = [
    "ReadCapstoneSubmissionContentInput",
    "ReadCapstoneSubmissionContentOutput",
    "read_capstone_submission_content",
]
