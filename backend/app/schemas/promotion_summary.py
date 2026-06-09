"""Promotion screen aggregator schemas.

The Promotion UI renders four things from this single payload:
  1. Four ladder rungs with live state (done / current / locked).
  2. Overall progress percentage (drives the topbar progress bar).
  3. Role transition copy ("Python Developer → Data Analyst").
  4. Gate status — does the student qualify, and have they been promoted yet?
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RungState = Literal["done", "current", "locked"]
GateStatus = Literal[
    "not_ready",  # at least one rung still locked or current
    "ready_to_promote",  # all four rungs done, takeover should fire
    "promoted",  # student already crossed the gate
]


class PromotionRung(BaseModel):
    kind: Literal[
        "lessons_foundation",  # rung 1: first ~50% of lessons
        "lessons_complete",  # rung 2: all enrolled lessons
        "capstone_submitted",  # rung 3: capstone exercise has a submission
        "interviews_complete",  # rung 4: 2+ completed practice interviews
    ]
    title: str
    detail: str
    state: RungState
    progress: int  # 0..100, used for the current rung's pulse intensity
    short_label: str  # ladder-rung label (compact)


class PromotionRoleTransition(BaseModel):
    from_role: str
    to_role: str


class PromotionStats(BaseModel):
    completed_lessons: int
    total_lessons: int
    due_card_count: int
    completed_interviews: int
    capstone_submissions: int


class PromotionSummaryResponse(BaseModel):
    overall_progress: int  # 0..100, drives topbar
    rungs: list[PromotionRung]  # always 4 rungs in display order
    role: PromotionRoleTransition
    stats: PromotionStats
    gate_status: GateStatus
    promoted_at: datetime | None
    promoted_to_role: str | None
    user_first_name: str | None


class PromotionConfirmRequest(BaseModel):
    """No body — confirm fires when the student dismisses the takeover."""

    pass


class PromotionConfirmResponse(BaseModel):
    promoted_at: datetime
    promoted_to_role: str
