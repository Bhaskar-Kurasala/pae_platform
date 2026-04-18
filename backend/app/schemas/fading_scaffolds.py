from pydantic import BaseModel


class FadedScaffoldResponse(BaseModel):
    attempt_number: int
    allowed_levels: list[str]
    faded: bool
    reason: str
