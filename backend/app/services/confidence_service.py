"""Confidence calibration (P3 3A-7).

Overconfidence is the strongest predictor of gaps. After a tutor has given
the student two or three substantive answers, it should ask "on a 1-5
scale, how confident are you on this?" — once per session. The value is
captured on a dedicated endpoint so the tutor's reply stream stays clean.

This module provides:
  - `CONFIDENCE_CALIBRATION_OVERLAY`: the prompt directive appended to
    tutor turns so the model knows when (and when not) to ask.
  - `record_report`: async writer for the `confidence_reports` table.
  - A value validator kept separate from Pydantic so service callers can
    surface a clear error before touching the DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.confidence_report import ConfidenceReport

log = structlog.get_logger()


CONFIDENCE_CALIBRATION_OVERLAY = (
    "\n\n---\nConfidence calibration: once you have given this student two or "
    "three substantive answers in this conversation on the same topic, add a "
    "short sentence at the end of your next reply asking them to rate their "
    "confidence on a 1-5 scale (1 = lost, 5 = could teach it). Only ask once "
    "per conversation — if you have already asked earlier in this thread, do "
    "not ask again. Do not ask after purely factual or one-line answers, after "
    "error-paste debugging, or in the first two turns of a conversation."
)


VALID_VALUES = frozenset({1, 2, 3, 4, 5})


def validate_value(value: int) -> int:
    """Clamp/validate a confidence value; raise ValueError if out of range."""
    if value not in VALID_VALUES:
        raise ValueError(f"confidence value must be 1-5, got {value}")
    return value


async def record_report(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    value: int,
    skill_id: uuid.UUID | None = None,
    asked_at: datetime | None = None,
    answered_at: datetime | None = None,
) -> ConfidenceReport:
    """Persist a confidence report. Caller owns the commit.

    `answered_at` defaults to the current UTC time. `asked_at` is optional
    so clients that don't track when the prompt was shown still write a
    valid row.
    """
    validate_value(value)
    row = ConfidenceReport(
        user_id=user_id,
        skill_id=skill_id,
        value=value,
        asked_at=asked_at,
        answered_at=answered_at or datetime.now(UTC),
    )
    db.add(row)
    log.info(
        "tutor.confidence_reported",
        user_id=str(user_id),
        skill_id=str(skill_id) if skill_id else None,
        value=value,
    )
    return row
