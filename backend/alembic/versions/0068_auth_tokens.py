"""auth_tokens table — single token table for all email-driven flows.

Revision ID: 0068
Revises: 0067
Create Date: 2026-05-13

Architectural decision D-A (Batch 1 Auth & Email Infrastructure):
One auth_tokens table covers password_reset, email_verify, and email_change
token flows. Storing sha256(token) prevents a DB-leak from being
password-leak-equivalent. Token expiry per type:
  - password_reset : 1 hour
  - email_verify   : 24 hours
  - email_change   : 1 hour

Down-migration cleanly reverses by dropping the table and its enum type.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0068_auth_tokens"
down_revision = "0067_users_daily_cost_ceiling"
branch_labels = None
depends_on = None

_TOKEN_TYPE_ENUM = "auth_token_type"
_TABLE = "auth_tokens"


def upgrade() -> None:
    # Create the enum type idempotently via PL/pgSQL exception guard.
    # `CREATE TYPE … IF NOT EXISTS` isn't available until PG 9.6+ and
    # asyncpg's dialect sometimes bypasses checkfirst on Enum.create(),
    # so we use the DO block pattern which is universally safe.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "  CREATE TYPE auth_token_type AS ENUM "
            "    ('password_reset', 'email_verify', 'email_change'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$"
        )
    )

    # Use raw SQL for the CREATE TABLE so SQLAlchemy's event-driven
    # Enum.create() never fires a second time on the column type.
    # The enum type is already in the DB from the DO block above.
    op.execute(
        sa.text(
            "CREATE TABLE auth_tokens ("
            "  id UUID PRIMARY KEY, "
            "  user_id UUID NOT NULL, "
            "  token_hash VARCHAR(64) NOT NULL UNIQUE, "
            "  token_type auth_token_type NOT NULL, "
            "  expires_at TIMESTAMPTZ NOT NULL, "
            "  used_at TIMESTAMPTZ, "
            "  ip_address VARCHAR(45), "
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "  CONSTRAINT fk_auth_tokens_user_id "
            "    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            ")"
        )
    )

    # Fast lookup: find a user's unused tokens of a given type.
    op.create_index(
        "ix_auth_tokens_user_type_used",
        _TABLE,
        ["user_id", "token_type", "used_at"],
    )
    # Cleanup job: efficiently find all expired tokens.
    op.create_index(
        "ix_auth_tokens_expires_at",
        _TABLE,
        ["expires_at"],
    )
    # Hash lookup on validate path (most frequent read).
    op.create_index(
        "ix_auth_tokens_token_hash",
        _TABLE,
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_token_hash", table_name=_TABLE)
    op.drop_index("ix_auth_tokens_expires_at", table_name=_TABLE)
    op.drop_index("ix_auth_tokens_user_type_used", table_name=_TABLE)
    op.drop_table(_TABLE)
    sa.Enum(name=_TOKEN_TYPE_ENUM).drop(op.get_bind(), checkfirst=True)
