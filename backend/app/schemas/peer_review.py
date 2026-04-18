from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PeerReviewSubmit(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class PeerReviewAssignmentItem(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    submission_id: UUID
    reviewer_id: UUID
    rating: int | None
    comment: str | None
    completed_at: datetime | None
    created_at: datetime


class PendingReviewsResponse(BaseModel):
    assignments: list[PeerReviewAssignmentItem]


class SubmissionPeerReviewsResponse(BaseModel):
    reviews: list[PeerReviewAssignmentItem]
