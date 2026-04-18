from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReviewCardItem(BaseModel):
    card_id: UUID
    concept_key: str
    prompt: str
    days_overdue: int


class WeeklyReviewResponse(BaseModel):
    generated_at: datetime
    cards: list[ReviewCardItem]
