"""Studio code execution endpoint (P1-B-4) + quality feedback (P2-08)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.quality_service import analyze_quality
from app.services.sandbox_service import run_python

router = APIRouter(prefix="/execute", tags=["execute"])


class ExecuteRequest(BaseModel):
    code: str = Field(..., max_length=50_000)
    timeout_seconds: float = Field(5.0, gt=0, le=15.0)


class TraceEventResponse(BaseModel):
    line: int
    locals: dict[str, str]


class QualityIssueResponse(BaseModel):
    rule: str
    severity: Literal["info", "warning"]
    line: int
    message: str


class QualityResponse(BaseModel):
    issues: list[QualityIssueResponse]
    score: int
    summary: str


class ExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    error: str | None
    events: list[TraceEventResponse]
    quality: QualityResponse


@router.post("", response_model=ExecuteResponse)
async def execute_code(
    payload: ExecuteRequest,
    current_user: User = Depends(get_current_user),
) -> ExecuteResponse:
    result = run_python(payload.code, timeout_seconds=payload.timeout_seconds)
    quality_report = analyze_quality(payload.code)
    return ExecuteResponse(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        error=result.error,
        events=[
            TraceEventResponse(line=e.line, locals=e.locals) for e in result.events
        ],
        quality=QualityResponse(
            issues=[
                QualityIssueResponse(
                    rule=i.rule, severity=i.severity, line=i.line, message=i.message,
                )
                for i in quality_report.issues
            ],
            score=quality_report.score,
            summary=quality_report.summary,
        ),
    )
