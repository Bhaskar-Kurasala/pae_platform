"""path + promotion screens — additive schema for production refactors

Adds:
  - users.promoted_at (timestamp, nullable)
  - users.promoted_to_role (string, nullable)

The Promotion screen aggregator computes the live rung state from existing
signals (progress, capstone submissions, interview sessions). These two new
columns persist the moment a student crosses ALL four rungs so the takeover
fires once and only once, and so we can render "Promoted on <date> to <role>"
on later visits without re-deriving from event timestamps.

The Path screen reuses existing tables (skills, lessons, exercises,
exercise_submissions) — no schema additions needed there. Lab data flows
from `Exercise` rows joined on `lesson_id`; durations come from
`Lesson.duration_seconds` and `Exercise.points`.

Strictly additive — no destructive operations.

Revision ID: 0048_path_promotion
Revises: 0047_payments_v2
Create Date: 2026-04-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048_path_promotion"
down_revision: str | None = "0047_payments_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("promoted_to_role", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "promoted_to_role")
    op.drop_column("users", "promoted_at")
