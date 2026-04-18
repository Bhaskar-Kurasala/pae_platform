from pydantic import BaseModel


class WorkedExampleResponse(BaseModel):
    available: bool
    exercise_title: str | None = None
    code_snippet: str | None = None
    note: str | None = None
    source: str | None = None
