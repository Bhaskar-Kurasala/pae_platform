"""Persistence-side schemas for `/api/v1/receipts/autopsy`.

The original `AutopsyResponse` (in `app/api/v1/routes/portfolio_autopsy.py`) is
the immediate POST response. These schemas describe rows fetched back later for
the Proof Portfolio view: a lightweight list item and a detail view that omits
the heavy `raw_request` / `code` blobs unless the caller explicitly wants them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PortfolioAutopsyListItem(BaseModel):
    """Compact row for the Proof Portfolio list view."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_title: str
    headline: str
    overall_score: int
    created_at: datetime


class PortfolioAutopsyDetailResponse(BaseModel):
    """Full record minus heavy fields (`raw_request`, `code`).

    Those two fields are excluded by default — the Proof view never needs the
    original code paste or the raw POST payload, and including them blows up
    response size. Add an explicit endpoint variant if a future caller does.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_title: str
    project_description: str
    headline: str
    overall_score: int
    axes: dict
    what_worked: list[str]
    what_to_do_differently: list[dict]
    production_gaps: list[str]
    next_project_seed: str | None
    created_at: datetime
    updated_at: datetime
