"""D11 Checkpoint 1 / Pass 3d §F.2 — lookup_prior_reviews.

Reads `feedback:code_review:*` rows from agent_memory for this
student. Returns past reviews with verdicts and key comments so
the agent can reference its own prior feedback ("you fixed the
bare-except since last time") and surface patterns
("third review in a row where naming is the main issue").

Reads only — no writes, no execution.

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
    layer="tools.senior_engineer.lookup_prior_reviews"
)


class LookupPriorReviewsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(
        description="The student whose past reviews to fetch."
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum prior reviews to return (most-recent first).",
    )


class PriorReview(BaseModel):
    """One past review row, projected to fields the LLM needs."""

    model_config = ConfigDict(extra="forbid")

    memory_id: uuid.UUID
    key: str
    value: dict[str, Any]
    created_at: datetime
    last_used_at: datetime


class LookupPriorReviewsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviews: list[PriorReview] = Field(default_factory=list)
    total_returned: int = Field(ge=0)


@tool(
    name="lookup_prior_reviews",
    description=(
        "Returns the student's recent code reviews from this agent, "
        "most-recent first. Use to track verdict trends, reference "
        "your own prior feedback, and detect recurring themes "
        "('third review with naming concerns'). Reads from "
        "agent_memory under feedback:code_review:* keys."
    ),
    input_schema=LookupPriorReviewsInput,
    output_schema=LookupPriorReviewsOutput,
    requires=("read:student_data",),
    cost_estimate=0.0,
    timeout_seconds=5.0,
)
async def lookup_prior_reviews(
    args: LookupPriorReviewsInput,
) -> LookupPriorReviewsOutput:
    """Structured recall via MemoryStore on feedback:code_review:* keys.

    Mode is structured (not hybrid) — we want exact key-prefix matches
    sorted by recency, not semantic similarity to a free-text query.
    The query string is the key prefix itself; MemoryStore's
    structured branch substring-matches keys (see _structured_search).
    """
    session = get_active_session()
    if session is None:
        raise RuntimeError(
            "lookup_prior_reviews called without an active session. "
            "The tool body relies on the contextvar set by call_agent."
        )

    try:
        store = MemoryStore(session)
        rows = await store.recall(
            "feedback:code_review",
            user_id=args.student_id,
            agent_name="senior_engineer",
            scope="user",
            k=args.limit,
            mode="structured",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lookup_prior_reviews.recall_failed",
            error=str(exc),
            student_id=str(args.student_id),
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            log.error(
                "lookup_prior_reviews.rollback_failed",
                original_error=str(exc),
                rollback_error=str(rollback_exc),
                student_id=str(args.student_id),
            )
        return LookupPriorReviewsOutput(reviews=[], total_returned=0)

    reviews = [
        PriorReview(
            memory_id=row.id,
            key=row.key,
            value=row.value,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )
        for row in rows
        if row.key.startswith("feedback:code_review")
    ]

    return LookupPriorReviewsOutput(
        reviews=reviews,
        total_returned=len(reviews),
    )


__all__ = [
    "LookupPriorReviewsInput",
    "LookupPriorReviewsOutput",
    "PriorReview",
    "lookup_prior_reviews",
]
