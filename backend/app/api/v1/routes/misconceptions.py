"""Misconception detection endpoint (P2-09).

Returns mental-model-level diagnostics for a code snippet. Consumed by the
Studio UI so students see *why* they're stuck, not just *what's wrong*.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.misconception_service import detect_misconceptions

router = APIRouter(prefix="/misconceptions", tags=["misconceptions"])


class AnalyzeRequest(BaseModel):
    code: str = Field(..., max_length=50_000)


class MisconceptionItem(BaseModel):
    code: str
    title: str
    line: int
    severity: Literal["info", "warning"]
    you_think: str
    actually: str
    fix_hint: str


class MisconceptionResponse(BaseModel):
    items: list[MisconceptionItem]
    summary: str


@router.post("/analyze", response_model=MisconceptionResponse)
async def analyze_misconceptions(
    payload: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
) -> MisconceptionResponse:
    report = detect_misconceptions(payload.code)
    return MisconceptionResponse(
        items=[
            MisconceptionItem(
                code=m.code,
                title=m.title,
                line=m.line,
                severity=m.severity,
                you_think=m.you_think,
                actually=m.actually,
                fix_hint=m.fix_hint,
            )
            for m in report.items
        ],
        summary=report.summary,
    )
