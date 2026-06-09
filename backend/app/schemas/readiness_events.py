"""Pydantic schemas for the readiness workspace events ingestion API.

The POST surface accepts EITHER a single event dict OR a wrapped batch
``{"events": [...]}``. A pre-validator coerces the single form into a
batch-of-one so the route handler only needs one code path.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RecordEventInput(BaseModel):
    view: str = Field(..., min_length=1, max_length=32)
    event: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] | None = None
    session_id: uuid.UUID | None = None
    occurred_at: datetime | None = None


class RecordEventBatchRequest(BaseModel):
    events: list[RecordEventInput] = Field(..., min_length=1, max_length=200)

    @model_validator(mode="before")
    @classmethod
    def _coerce_single_to_batch(cls, value: Any) -> Any:
        """Accept either a wrapped batch or a single bare event dict.

        The frontend sometimes posts one event at a time (view-change
        flush) and sometimes a flush-list (timer flush). Normalizing here
        lets the route stay one-shape.
        """
        if not isinstance(value, dict):
            return value
        if "events" in value:
            return value
        # Bare single-event payload — wrap it.
        if {"view", "event"}.issubset(value.keys()):
            return {"events": [value]}
        return value


class RecordEventBatchResponse(BaseModel):
    recorded: int = Field(..., ge=0)
    skipped: int = Field(..., ge=0)


class WorkspaceEventOut(BaseModel):
    id: uuid.UUID
    view: str
    event: str
    payload: dict[str, Any] | None = None
    session_id: uuid.UUID | None = None
    occurred_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceEventSummaryResponse(BaseModel):
    total: int = Field(..., ge=0)
    by_view: dict[str, int] = Field(default_factory=dict)
    by_event: dict[str, int] = Field(default_factory=dict)
    last_event_at: datetime | None = None
    since_days: int = Field(..., ge=1, le=90)
    generated_at: datetime
