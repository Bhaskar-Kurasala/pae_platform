"""Senior-engineer review endpoint (P2-04).

Returns a structured PR-style review of the submitted code. Non-streaming —
the client receives one JSON object.

D11 cutover (2026-05-15): the legacy ``get_agent("senior_engineer")`` call
broke because senior_engineer migrated from BaseAgent to AgenticBaseAgent and
no longer lives in the legacy AGENT_REGISTRY. This route now invokes the
agentic agent directly via ``get_agentic`` and adapts SeniorEngineerOutput
to the legacy SeniorReviewResponse contract so the frontend keeps working.
"""

from __future__ import annotations

import anthropic
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.primitives.communication import CallChain, get_agentic
from app.agents.senior_engineer import SeniorEngineerInput
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.agents.senior_engineer import SeniorEngineerOutput
from app.schemas.senior_review import (
    SeniorReviewComment,
    SeniorReviewRequest,
    SeniorReviewResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/senior-review", tags=["senior-review"])


def _adapt_to_legacy(output: SeniorEngineerOutput) -> SeniorReviewResponse:
    """Project the new agentic output onto the legacy pr_review shape.

    The frontend's SeniorReviewResponse expects pr_review fields. The agent
    may legitimately return chat_help (no code/question framing) or
    rubric_score (when a rubric was supplied), so we degrade those gracefully
    by synthesizing a "comment" verdict with the explanation as the headline.

    ``line`` is coerced to a positive int because the new schema allows None
    for whole-file comments but the legacy schema requires ``line >= 1``.
    """
    if output.mode == "pr_review":
        comments = [
            SeniorReviewComment(
                line=c.line if (c.line and c.line >= 1) else 1,
                severity=c.severity,
                message=c.message,
                suggested_change=c.suggested_change,
            )
            for c in output.comments
        ]
        return SeniorReviewResponse(
            verdict=output.verdict or "comment",
            headline=output.headline or "Review complete.",
            strengths=list(output.strengths),
            comments=comments,
            next_step=output.next_step or "Keep iterating.",
        )

    if output.mode == "chat_help":
        body = (output.explanation or "Review complete.")[:120]
        return SeniorReviewResponse(
            verdict="comment",
            headline=body,
            strengths=[],
            comments=[],
            next_step=(output.code_suggestion or "Try the suggested approach.")[:200],
        )

    # rubric_score
    head = (
        f"Score: {output.score}/100"
        if output.score is not None
        else "Rubric scoring complete."
    )
    return SeniorReviewResponse(
        verdict="comment",
        headline=head,
        strengths=[],
        comments=[],
        next_step=(output.rubric_feedback or "See feedback above.")[:200],
    )


@router.post("", response_model=SeniorReviewResponse)
@limiter.limit("10/minute")
async def request_senior_review(
    request: Request,
    payload: SeniorReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SeniorReviewResponse:
    agent = get_agentic("senior_engineer")

    from app.agents.agentic_base import AgentContext

    ctx = AgentContext(
        user_id=current_user.id,
        chain=CallChain.start_root(caller="senior_review_route", user_id=current_user.id),
        session=db,
        permissions=frozenset(
            {
                "read:agent_memory",
                "write:agent_memory",
                "read:student_data",
                "write:audit_log",
            }
        ),
    )

    agent_input = SeniorEngineerInput(
        code=payload.code,
        problem_context=payload.problem_context,
        mode="pr_review",
    )

    log.info(
        "senior_review.start",
        user_id=str(current_user.id),
        code_len=len(payload.code),
        has_context=bool(payload.problem_context),
    )

    try:
        result = await agent.execute(agent_input, ctx)
    except (anthropic.RateLimitError, anthropic.APITimeoutError) as exc:
        log.warning(
            "senior_review.rate_limited",
            user_id=str(current_user.id),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Reviewer is at capacity — try again in 30–60s.",
        ) from exc
    except anthropic.APIError as exc:
        log.error("senior_review.api_error", err=str(exc))
        raise HTTPException(
            status_code=502,
            detail="Service temporarily unavailable. Please try again.",
        ) from exc

    output_dict = result.output if isinstance(result.output, dict) else {}
    if output_dict.get("blocked"):
        raise HTTPException(
            status_code=400,
            detail=output_dict.get("block_reason", "Input failed safety checks."),
        )

    # The output safety gate may have wrapped the payload with an
    # ``output_text`` redaction; ``answer`` is the dispatch-layer projection.
    # Filter to fields the strict schema actually accepts.
    schema_fields = set(SeniorEngineerOutput.model_fields.keys())
    cleaned = {k: v for k, v in output_dict.items() if k in schema_fields}

    try:
        output = SeniorEngineerOutput.model_validate(cleaned)
    except Exception as exc:
        log.error("senior_review.validation_error", err=str(exc), output=output_dict)
        raise HTTPException(
            status_code=502, detail="Review response failed schema validation"
        ) from exc

    return _adapt_to_legacy(output)
