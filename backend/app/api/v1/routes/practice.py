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

import json
import uuid

import anthropic
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import AgentState
from app.agents.registry import _ensure_registered, get_agent
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.ai_review import AIReview
from app.models.user import User
from app.schemas.practice import (
    PracticeReviewListItem,
    PracticeReviewRequest,
    PracticeReviewResponse,
)
from app.schemas.senior_review import SeniorReviewResponse

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

    _ensure_registered()
    agent = get_agent("senior_engineer")

    state = AgentState(
        student_id=str(current_user.id),
        task="practice_review",
        context={
            "code": payload.code,
            "problem_context": payload.problem_context or "",
        },
    )

    log.info(
        "practice.review.start",
        user_id=str(current_user.id),
        problem_id=str(payload.problem_id) if payload.problem_id else None,
        code_len=len(payload.code),
    )

    try:
        new_state = await agent.execute(state)
    except anthropic.OverloadedError:
        log.warning("practice.review.api_overloaded", user_id=str(current_user.id))
        raise HTTPException(
            status_code=503,
            detail="Reviewer is temporarily busy — try again in a few seconds.",
        )
    except anthropic.APIError as exc:
        log.error("practice.review.api_error", err=str(exc))
        raise HTTPException(status_code=502, detail=f"Reviewer API error: {exc}")

    try:
        review_dict = json.loads(new_state.response or "{}")
    except json.JSONDecodeError as e:
        log.error("practice.review.parse_error", err=str(e))
        raise HTTPException(
            status_code=502, detail="Reviewer response was not parseable JSON"
        )

    try:
        review = SeniorReviewResponse.model_validate(review_dict)
    except Exception as e:
        log.error("practice.review.validation_error", err=str(e))
        raise HTTPException(
            status_code=502, detail="Reviewer response failed schema validation"
        )

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
