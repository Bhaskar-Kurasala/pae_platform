"""D16/CP3.1 — add nullable whatsapp_number column to users.

Closes the schema gap identified by D16 CP1 finding (n) and the
pre-flight audit's §5.1 / §9.1: the founder reframe assumes admin
reaches out to at-risk students via WhatsApp, but `users` carried no
phone/WhatsApp column, so the cockpit had nowhere to source the deep-
link target from.

Nullable text. Stored as a free-form string (E.164 hint in the schema
docstring); no format validation in v1 because admins source numbers
from existing channels and over-strict validation would block valid
edge cases (e.g., extension digits, country-code variants, transient
re-keys mid-onboarding).

No index needed. Lookups are admin-side only and always go through a
known student_id; whatsapp_number is never the search key.

Revision ID: 0065_users_whatsapp_number
Revises: 0064_courses_role_backfill
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065_users_whatsapp_number"
down_revision: str | None = "0064_courses_role_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("whatsapp_number", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "whatsapp_number")
