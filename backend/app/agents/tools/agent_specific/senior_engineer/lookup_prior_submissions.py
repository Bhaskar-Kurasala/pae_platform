"""D11 Checkpoint 1 / Pass 3d §F.2 — lookup_prior_submissions.

Semantic search over the student's past code submissions stored in
agent_memory under `submission:code:*` keys. Returns the N most
similar prior submissions so the agent can reference patterns
("you used the same try/except shape last time"), call out
regressions ("this used to handle the empty case; now it doesn't"),
or just contextualize the review.

Reads only — no writes, no execution. Sandbox tools per Pass 3d §E.3
are deferred to D14 (see D11 prompt's sandbox deferral section).

Permissions: read:student_data — set on senior_engineer's permission
ClassVar; the executor checks it before dispatching.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from app.agents.primitives.communication import get_active_session
from app.agents.primitives.memory import MemoryStore
from app.agents.primitives.tools import tool

log = structlog.get_logger().bind(
    layer="tools.senior_engineer.lookup_prior_submissions"
)


class LookupPriorSubmissionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student whose submissions to search."
    )
    similar_to_code: str = Field(
        min_length=1,
        max_length=20_000,
        description=(
            "The code (or a summary of it) to search semantically. "
            "MemoryStore embeds this and finds the closest prior "
            "submissions by cosine similarity."
        ),
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum prior submissions to return.",
    )


class PriorSubmission(BaseModel):
    """One prior submission row, projected to fields the LLM needs."""

    model_config = ConfigDict(extra="forbid")

    memory_id: uuid.UUID
    key: str
    value: dict[str, Any]
    similarity: float | None = Field(
        default=None,
        description=(
            "Cosine-similarity score (0.0-1.0) when the row came back "
            "via semantic search; None for structured-match hits."
        ),
    )
    created_at: datetime
    last_used_at: datetime


class LookupPriorSubmissionsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissions: list[PriorSubmission] = Field(default_factory=list)
    total_returned: int = Field(ge=0)


@tool(
    name="lookup_prior_submissions",
    description=(
        "Returns the student's most semantically-similar prior code "
        "submissions. Use to ground review comments in patterns the "
        "student has shown before, or to call out regressions when a "
        "prior version handled a case this version misses. Reads from "
        "agent_memory; no execution, no sandbox."
    ),
    input_schema=LookupPriorSubmissionsInput,
    output_schema=LookupPriorSubmissionsOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=8.0,
)
async def lookup_prior_submissions(
    args: LookupPriorSubmissionsInput,
) -> LookupPriorSubmissionsOutput:
    """Recall via MemoryStore filtered to senior_engineer's submission keys.

    Per Pass 3c E2 §A.5, prior submissions live under
    `submission:code:*` keys. We use MemoryStore's hybrid recall
    (semantic + structured) so a query that includes a code-shape
    fragment hits both the embedding index and the substring match
    on the key.
    """
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "lookup_prior_submissions called without an active session. "
            "The tool body relies on the contextvar set by call_agent."
        )

    try:
        store = MemoryStore(session)
        # agent_name='senior_engineer' filters to memories this agent
        # itself wrote — submissions other agents stashed under similar
        # keys aren't surfaced here. The structured branch of hybrid
        # recall additionally substring-matches "submission:code" so
        # only the right key family comes back.
        rows = await store.recall(
            f"submission:code {args.similar_to_code}",
            user_id=args.student_id,
            agent_name="senior_engineer",
            scope="user",
            k=args.limit,
            mode="hybrid",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lookup_prior_submissions.recall_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        # asyncpg-rollback discipline per
        # docs/followups/asyncpg-rollback-discipline.md
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "lookup_prior_submissions.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return LookupPriorSubmissionsOutput(
            submissions=[], total_returned=0
        )

    # Filter to rows whose keys are actually in the submission family —
    # MemoryStore's hybrid recall may surface other keys via the
    # semantic branch when their embeddings happen to match the query.
    submissions = [
        PriorSubmission(
            memory_id=row.id,
            key=row.key,
            value=row.value,
            similarity=row.similarity,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )
        for row in rows
        if row.key.startswith("submission:code")
    ]

    return LookupPriorSubmissionsOutput(
        submissions=submissions,
        total_returned=len(submissions),
    )


__all__ = [
    "LookupPriorSubmissionsInput",
    "LookupPriorSubmissionsOutput",
    "PriorSubmission",
    "lookup_prior_submissions",
]
