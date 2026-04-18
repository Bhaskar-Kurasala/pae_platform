from pydantic import BaseModel, Field


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
