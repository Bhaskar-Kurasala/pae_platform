"""Senior-engineer review endpoint (P2-04).

Returns a structured PR-style review of the submitted code. Non-streaming —
the client receives one JSON object.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.base_agent import AgentState
from app.agents.registry import _ensure_registered, get_agent
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.senior_review import SeniorReviewRequest, SeniorReviewResponse

log = structlog.get_logger()

router = APIRouter(prefix="/senior-review", tags=["senior-review"])


@router.post("", response_model=SeniorReviewResponse)
@limiter.limit("10/minute")
async def request_senior_review(
    request: Request,
    payload: SeniorReviewRequest,
    current_user: User = Depends(get_current_user),
) -> SeniorReviewResponse:
    _ensure_registered()
    agent = get_agent("senior_engineer")

    state = AgentState(
        student_id=str(current_user.id),
        task="senior_review",
        context={
            "code": payload.code,
            "problem_context": payload.problem_context or "",
        },
    )

    log.info(
        "senior_review.start",
        user_id=str(current_user.id),
        code_len=len(payload.code),
        has_context=bool(payload.problem_context),
    )

    new_state = await agent.execute(state)
    try:
        review = json.loads(new_state.response or "{}")
    except json.JSONDecodeError as e:
        log.error("senior_review.parse_error", err=str(e))
        raise HTTPException(status_code=502, detail="Review response was not parseable JSON")

    try:
        return SeniorReviewResponse.model_validate(review)
    except Exception as e:
        log.error("senior_review.validation_error", err=str(e), review=review)
        raise HTTPException(status_code=502, detail="Review response failed schema validation")
