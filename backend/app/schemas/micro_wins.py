from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WinKind = Literal[
    "misconception_resolved", "lesson_completed", "hard_exercise_passed"
]


class MicroWinItem(BaseModel):
    kind: WinKind
    label: str
    occurred_at: datetime


class MicroWinsResponse(BaseModel):
    wins: list[MicroWinItem]
