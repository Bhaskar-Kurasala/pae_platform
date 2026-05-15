"""Unified /practice surface — Phase B1 vertical slice.

POST /api/v1/practice/review — runs the senior_engineer agent on the user's
code, persists the result to ``ai_reviews``, and returns the structured
review payload along with the row id and timestamp.

GET /api/v1/practice/reviews — lists prior reviews for the current user,
optionally scoped to one problem. Most recent first.

Rate-limited per-user (not per-IP) so shared NATs don't squeeze multiple
students. AI calls are expensive: 20/hour/user.
"""

from __future__ import annotations

import uuid

import anthropic
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agentic_base import AgentContext
from app.agents.primitives.communication import CallChain, get_agentic
from app.agents.senior_engineer import SeniorEngineerInput
from app.api.v1.routes.senior_review import _adapt_to_legacy
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.ai_review import AIReview
from app.models.user import User
from app.schemas.agents.senior_engineer import SeniorEngineerOutput
from app.schemas.practice import (
    PracticeReviewListItem,
    PracticeReviewRequest,
    PracticeReviewResponse,
    RunOutputSnapshot,
)
from app.schemas.senior_review import SeniorReviewResponse


def _format_run_output(snapshot: RunOutputSnapshot | None) -> str | None:
    """Render the sandbox run as a structured text block for the agent.

    The senior_engineer prompt was rewritten so a populated [Run results]
    block licenses the agent to cite the outcome verbatim. When the student
    hasn't run anything yet (snapshot is None), we return None — the agent
    then reasons about the code as pure text, per the original constraint.
    """
    if snapshot is None:
        return None

    parts: list[str] = []
    if snapshot.exit_code is not None:
        outcome = "success" if snapshot.exit_code == 0 else "failure"
        parts.append(f"Exit code: {snapshot.exit_code} ({outcome})")
    if snapshot.timed_out:
        parts.append("Status: TIMED OUT")
    if snapshot.quality_score is not None:
        parts.append(f"Heuristic quality score: {snapshot.quality_score}/100")
    if snapshot.quality_summary:
        parts.append(f"Quality summary: {snapshot.quality_summary}")
    if snapshot.stdout.strip():
        parts.append(f"--- STDOUT (last 4KB) ---\n{snapshot.stdout.strip()}")
    if snapshot.stderr.strip():
        parts.append(f"--- STDERR (last 4KB) ---\n{snapshot.stderr.strip()}")

    if not parts:
        return None

    block = "\n\n".join(parts)
    # SeniorEngineerInput.test_results caps at 4_000 chars; trim from the
    # left (stdout/stderr) so the structural fields at the top survive.
    if len(block) > 3_900:
        block = block[-3_900:]
    return block

log = structlog.get_logger()

router = APIRouter(prefix="/practice", tags=["practice"])


def _user_key(request: Request) -> str:
    """slowapi key function — limit by authenticated user, fall back to IP.

    We can't depend-inject get_current_user inside slowapi's key_func, so we
    read the JWT off the request scope state if any middleware stashed it.
    Falls back to remote-addr for unauthenticated probes (which the endpoint
    will then reject anyway).
    """
    user = getattr(request.state, "user", None)
    if user is not None and getattr(user, "id", None) is not None:
        return f"user:{user.id}"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


@router.post("/review", response_model=PracticeReviewResponse)
@limiter.limit("20/hour", key_func=_user_key)
async def request_practice_review(
    request: Request,
    payload: PracticeReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PracticeReviewResponse:
    # Stash for the rate-limit key function on subsequent calls in the same
    # request (no-op for the first call, but keeps the contract honest).
    request.state.user = current_user

    agent = get_agentic("senior_engineer")

    ctx = AgentContext(
        user_id=current_user.id,
        chain=CallChain.start_root(caller="practice_review_route", user_id=current_user.id),
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

    test_results = _format_run_output(payload.run_output)

    agent_input = SeniorEngineerInput(
        code=payload.code,
        problem_context=payload.problem_context,
        test_results=test_results,
        mode="pr_review",
    )

    log.info(
        "practice.review.start",
        user_id=str(current_user.id),
        problem_id=str(payload.problem_id) if payload.problem_id else None,
        code_len=len(payload.code),
    )

    try:
        result = await agent.execute(agent_input, ctx)
    except anthropic.OverloadedError as exc:
        log.warning("practice.review.api_overloaded", user_id=str(current_user.id))
        raise HTTPException(
            status_code=503,
            detail="Reviewer is temporarily busy — try again in a few seconds.",
        ) from exc
    except anthropic.APIError as exc:
        log.error("practice.review.api_error", err=str(exc))
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

    schema_fields = set(SeniorEngineerOutput.model_fields.keys())
    cleaned = {k: v for k, v in output_dict.items() if k in schema_fields}

    try:
        output = SeniorEngineerOutput.model_validate(cleaned)
    except Exception as exc:
        log.error("practice.review.validation_error", err=str(exc), output=output_dict)
        raise HTTPException(
            status_code=502, detail="Reviewer response failed schema validation"
        ) from exc

    review = _adapt_to_legacy(output)

    row = AIReview(
        id=uuid.uuid4(),
        user_id=current_user.id,
        problem_id=payload.problem_id,
        code_snapshot=payload.code,
        review=review.model_dump(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    log.info(
        "practice.review.saved",
        review_id=str(row.id),
        user_id=str(current_user.id),
        problem_id=str(payload.problem_id) if payload.problem_id else None,
        verdict=review.verdict,
    )

    return PracticeReviewResponse(
        id=row.id,
        problem_id=row.problem_id,
        review=review,
        created_at=row.created_at,
    )


@router.get("/reviews", response_model=list[PracticeReviewListItem])
async def list_my_reviews(
    problem_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PracticeReviewListItem]:
    stmt = (
        select(AIReview)
        .where(AIReview.user_id == current_user.id)
        .order_by(AIReview.created_at.desc())
        .limit(limit)
    )
    if problem_id is not None:
        stmt = stmt.where(AIReview.problem_id == problem_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        PracticeReviewListItem(
            id=r.id,
            problem_id=r.problem_id,
            review=SeniorReviewResponse.model_validate(r.review),
            created_at=r.created_at,
        )
        for r in rows
    ]
