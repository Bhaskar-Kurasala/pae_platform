"""users table auth extensions — failed_login_count, locked_until.

Revision ID: 0069
Revises: 0068
Create Date: 2026-05-13

Adds the two columns required for Batch 1 account-lockout (D-C):
  - failed_login_count : consecutive failed login attempts; reset on
                         successful login or password reset.
  - locked_until       : timestamp until which the account is locked;
                         NULL means not locked. Sliding window — a
                         failed attempt while locked extends this value.

GRANDFATHER DECISION (SC-1, Batch 1 Auth pre-flight):
  All users existing as of migration application are SET to
  is_verified = TRUE.

  (a) Cutoff: every row in the users table at the moment this migration
      runs is grandfathered. Rows inserted after this migration are
      subject to the new verification-required policy.

  (b) Rationale: the verification-required policy did not exist prior to
      Batch 1. All pre-batch registrations went through an endpoint that
      set is_verified = FALSE by default (column existed from migration
      0001) but never enforced verification before allowing login.
      Blocking these users post-migration would be a regression with no
      user-visible prior notice.

  (c) Post-migration policy: new registrations via POST /api/v1/auth/register
      receive is_verified = FALSE and must confirm their email via the
      verify-email flow before login is allowed. OAuth signups (GitHub,
      Google) continue to auto-set is_verified = TRUE because the provider
      already verified the email.

  The is_verified column itself is not added here (it was added in
  migration 0001_initial_schema.py). Only the grandfather UPDATE is applied.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0069_users_auth_extensions"
down_revision = "0068_auth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Account lockout columns (D-C) ──────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ── Grandfather UPDATE (SC-1) ───────────────────────────────────────
    # Set all pre-existing users as verified. See module docstring for the
    # three-part rationale. No WHERE clause is intentional — we want every
    # user created before this migration to be treated as verified,
    # regardless of their current is_verified value.
    op.execute(
        sa.text(
            "UPDATE users SET is_verified = TRUE "
            "WHERE is_deleted = FALSE OR is_deleted = TRUE"
            # Deliberately includes soft-deleted users so that if they
            # are ever restored they don't get locked out either.
        )
    )


def downgrade() -> None:
    # Removing the columns is safe; the grandfather UPDATE is not reversed
    # (we can't distinguish pre-batch from post-batch users after the fact).
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
