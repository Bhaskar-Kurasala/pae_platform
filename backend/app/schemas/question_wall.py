from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class QuestionPostCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    parent_id: UUID | None = None


class QuestionVoteRequest(BaseModel):
    kind: Literal["upvote", "flag"]


class QuestionPostItem(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    lesson_id: UUID
    author_id: UUID
    parent_id: UUID | None
    body: str
    upvote_count: int
    flag_count: int
    created_at: datetime


class LessonQuestionsResponse(BaseModel):
    lesson_id: UUID
    posts: list[QuestionPostItem]


class QuestionRepliesResponse(BaseModel):
    parent_id: UUID
    replies: list[QuestionPostItem]
