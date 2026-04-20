"""Pydantic schemas for chat context-attach (P1-7).

Covers `GET /api/v1/chat/context-suggestions` and the `context_refs` field
on `POST /api/v1/agents/stream`. Refs are kind-tagged so a single list can
carry heterogeneous references (a submission, a lesson, an exercise) without
separate fields. The backend resolves each ref server-side — the client
never has to ship the full body of a submission or lesson back.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ContextKind = Literal["submission", "lesson", "exercise"]


class ContextRef(BaseModel):
    """A single context reference the client wants prepended to the turn.

    Kept deliberately minimal — `kind` drives the lookup path server-side,
    `id` is the row's UUID. Any display metadata (title, filename, etc.) is
    re-derived from the DB rather than trusting the client.
    """

    kind: ContextKind
    id: uuid.UUID


class ContextSuggestionSubmission(BaseModel):
    """Recent submission the student might want to ask about."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exercise_title: str
    submitted_at: datetime


class ContextSuggestionLesson(BaseModel):
    """Current or most-recently-visited lesson."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str


class ContextSuggestionExercise(BaseModel):
    """Exercise the student is currently working on."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str


class ContextSuggestionsResponse(BaseModel):
    """Bundle of context the picker renders when it opens."""

    submissions: list[ContextSuggestionSubmission] = Field(default_factory=list)
    lessons: list[ContextSuggestionLesson] = Field(default_factory=list)
    exercises: list[ContextSuggestionExercise] = Field(default_factory=list)
