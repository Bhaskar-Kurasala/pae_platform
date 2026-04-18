from typing import Literal

from pydantic import BaseModel, Field

DiagnosticCTADecision = Literal["opted_in", "dismissed", "snoozed"]


class DiagnosticCTARequest(BaseModel):
    decision: DiagnosticCTADecision
    note: str | None = Field(default=None, max_length=200)


class DiagnosticCTAResponse(BaseModel):
    decision: DiagnosticCTADecision
    recorded: bool


class DiagnosticScaleItem(BaseModel):
    rating: int
    label: str


class DiagnosticQuestion(BaseModel):
    id: str
    skill_slug: str
    prompt: str


class DiagnosticQuestionsResponse(BaseModel):
    questions: list[DiagnosticQuestion]
    scale: list[DiagnosticScaleItem]


class DiagnosticAnswer(BaseModel):
    skill_slug: str
    rating: int = Field(ge=1, le=5)


class DiagnosticSubmission(BaseModel):
    answers: list[DiagnosticAnswer]


class DiagnosticSubmitResponse(BaseModel):
    states_updated: int
