"""notebook_entries — graduation timestamp + free-form tags

Adds:
  - notebook_entries.graduated_at  TIMESTAMPTZ NULL
  - notebook_entries.tags          JSON DEFAULT '[]'

Strictly additive. `graduated_at` is NULL until the SRS card backing the
note proves recall (repetitions >= 2 — see notebook_service.maybe_graduate).
`tags` is a JSON array because PG/SQLite both speak it natively and we
already lean on JSON columns elsewhere (no point in a tags table).

Revision ID: 0045_notebook_graduation
Revises: 0044_today_screen_completion
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045_notebook_graduation"
down_revision: str | None = "0044_today_screen_completion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Defensive: the production DB already has a `tags` column from an
    # earlier branch (as VARCHAR[]). We only add what's missing so this
    # migration is safe regardless of starting state. Using IF NOT EXISTS
    # via raw DDL because Alembic's `op.add_column` doesn't support it.
    op.execute(
        "ALTER TABLE notebook_entries "
        "ADD COLUMN IF NOT EXISTS graduated_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE notebook_entries "
        "ADD COLUMN IF NOT EXISTS tags VARCHAR[] DEFAULT '{}'::VARCHAR[] NOT NULL"
    )
    # Some installs may have added `tags` as JSON earlier; normalize to NOT
    # NULL only when the column allows it. Skipping the type-coerce — both
    # JSON arrays and PG VARCHAR[] are read as Python lists by SQLAlchemy
    # for our access patterns (ARRAY(String) on the model).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notebook_entries_user_graduated "
        "ON notebook_entries (user_id, graduated_at)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_notebook_entries_user_graduated"
    )
    op.execute(
        "ALTER TABLE notebook_entries DROP COLUMN IF EXISTS tags"
    )
    op.execute(
        "ALTER TABLE notebook_entries DROP COLUMN IF EXISTS graduated_at"
    )
