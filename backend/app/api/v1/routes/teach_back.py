"""Teach-back endpoint (P2-11).

POST /api/v1/teach-back/evaluate
  { concept, explanation, reference_notes? } → structured rubric evaluation

Thin controller — real work lives in `teach_back_service`.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.teach_back_service import evaluate_explanation

router = APIRouter(prefix="/teach-back", tags=["teach-back"])


class EvaluateRequest(BaseModel):
    concept: str = Field(..., min_length=1, max_length=300)
    explanation: str = Field(..., min_length=1, max_length=8_000)
    reference_notes: str | None = Field(None, max_length=12_000)


class RubricScoreResponse(BaseModel):
    score: int
    evidence: str


class EvaluateResponse(BaseModel):
    accuracy: RubricScoreResponse
    completeness: RubricScoreResponse
    beginner_clarity: RubricScoreResponse
    would_beginner_understand: bool
    missing_ideas: list[str]
    best_sentence: str
    follow_up: str


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(
    payload: EvaluateRequest,
    current_user: User = Depends(get_current_user),
) -> EvaluateResponse:
    try:
        result = await evaluate_explanation(
            concept=payload.concept,
            explanation=payload.explanation,
            reference_notes=payload.reference_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Evaluation parse failed: {exc}") from exc

    return EvaluateResponse(
        accuracy=RubricScoreResponse(**result.accuracy.__dict__),
        completeness=RubricScoreResponse(**result.completeness.__dict__),
        beginner_clarity=RubricScoreResponse(**result.beginner_clarity.__dict__),
        would_beginner_understand=result.would_beginner_understand,
        missing_ideas=result.missing_ideas,
        best_sentence=result.best_sentence,
        follow_up=result.follow_up,
    )
