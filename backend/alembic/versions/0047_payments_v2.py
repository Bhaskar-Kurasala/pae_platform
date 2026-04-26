"""payments v2 — Razorpay-ready order + entitlement + webhook ledger

Six new tables that close the gaps for production-grade catalog purchases:

  * orders                  — user's intent to buy a course or bundle
  * payment_attempts        — per-attempt txn rows against an order
  * payment_webhook_events  — append-only ledger keyed UNIQUE on
                              (provider, provider_event_id) for dedup
  * course_entitlements     — authoritative "user has access" record;
                              partial-unique on (user_id, course_id)
                              WHERE revoked_at IS NULL
  * course_bundles          — multi-course package SKUs
  * refunds                 — per-refund records linked to order +
                              attempt + provider refund id

Plus two columns on `courses`:
  * bullets   JSON  — per-card outcome bullets (replaces hard-coded UI)
  * metadata_ JSON  — keys: lesson_count, lab_count, capstone_title,
                            est_hours, est_weeks, completion_pct,
                            placement_pct, level_label, ribbon_text,
                            accent_color, salary_tooltip{...}

Strictly additive. Existing `payments` and `enrollments` tables stay
untouched — entitlement layer SITS ON TOP and old free-course flows
continue to work during migration. Uses `IF NOT EXISTS` everywhere so
the migration is safe across branches.

Revision ID: 0047_payments_v2
Revises: 0046_readiness_workspace
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047_payments_v2"
down_revision: str | None = "0046_readiness_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- courses: add bullets + metadata columns ------------------------
    op.execute(
        "ALTER TABLE courses "
        "ADD COLUMN IF NOT EXISTS bullets JSON NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE courses "
        "ADD COLUMN IF NOT EXISTS metadata JSON NOT NULL DEFAULT '{}'"
    )

    # --- course_bundles -------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS course_bundles (
            id UUID PRIMARY KEY,
            slug VARCHAR(120) UNIQUE NOT NULL,
            title VARCHAR(200) NOT NULL,
            description TEXT NULL,
            price_cents INTEGER NOT NULL DEFAULT 0,
            currency VARCHAR(8) NOT NULL DEFAULT 'INR',
            course_ids JSON NOT NULL DEFAULT '[]',
            metadata JSON NOT NULL DEFAULT '{}',
            is_published BOOLEAN NOT NULL DEFAULT FALSE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_course_bundles_slug "
        "ON course_bundles (slug)"
    )

    # --- orders ---------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            target_type VARCHAR(20) NOT NULL,
            target_id UUID NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency VARCHAR(8) NOT NULL DEFAULT 'INR',
            provider VARCHAR(20) NOT NULL,
            provider_order_id VARCHAR(255) NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'created',
            failure_reason TEXT NULL,
            receipt_number VARCHAR(40) NULL UNIQUE,
            gst_breakdown JSON NULL,
            metadata JSON NOT NULL DEFAULT '{}',
            paid_at TIMESTAMP WITH TIME ZONE NULL,
            fulfilled_at TIMESTAMP WITH TIME ZONE NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_user_created "
        "ON orders (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_provider_order "
        "ON orders (provider, provider_order_id) "
        "WHERE provider_order_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_status "
        "ON orders (status)"
    )

    # --- payment_attempts -----------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_attempts (
            id UUID PRIMARY KEY,
            order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            provider VARCHAR(20) NOT NULL,
            provider_payment_id VARCHAR(255) NULL,
            provider_signature VARCHAR(512) NULL,
            amount_cents INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'created',
            failure_reason TEXT NULL,
            raw_response JSON NULL,
            attempted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_attempts_order "
        "ON payment_attempts (order_id, attempted_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_attempts_provider_payment "
        "ON payment_attempts (provider, provider_payment_id) "
        "WHERE provider_payment_id IS NOT NULL"
    )

    # --- payment_webhook_events -----------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_webhook_events (
            id UUID PRIMARY KEY,
            provider VARCHAR(20) NOT NULL,
            provider_event_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(80) NOT NULL,
            raw_body BYTEA NOT NULL,
            signature VARCHAR(512) NULL,
            signature_valid BOOLEAN NOT NULL DEFAULT FALSE,
            related_order_id UUID NULL REFERENCES orders(id) ON DELETE SET NULL,
            processed_at TIMESTAMP WITH TIME ZONE NULL,
            error TEXT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_webhook_provider_event "
        "ON payment_webhook_events (provider, provider_event_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_webhook_event_type "
        "ON payment_webhook_events (event_type, created_at DESC)"
    )

    # --- course_entitlements --------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS course_entitlements (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            source VARCHAR(20) NOT NULL,
            source_ref UUID NULL,
            granted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMP WITH TIME ZONE NULL,
            expires_at TIMESTAMP WITH TIME ZONE NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_course_entitlements_user "
        "ON course_entitlements (user_id)"
    )
    # Partial unique: at most one ACTIVE entitlement per (user, course).
    # Revoked rows are kept for audit; new grants insert a fresh row.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_course_entitlements_active "
        "ON course_entitlements (user_id, course_id) "
        "WHERE revoked_at IS NULL"
    )

    # --- refunds --------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id UUID PRIMARY KEY,
            order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            payment_attempt_id UUID NULL
                REFERENCES payment_attempts(id) ON DELETE SET NULL,
            provider VARCHAR(20) NOT NULL,
            provider_refund_id VARCHAR(255) NULL,
            amount_cents INTEGER NOT NULL,
            currency VARCHAR(8) NOT NULL DEFAULT 'INR',
            reason TEXT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            raw_response JSON NULL,
            processed_at TIMESTAMP WITH TIME ZONE NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_refunds_provider_refund "
        "ON refunds (provider, provider_refund_id) "
        "WHERE provider_refund_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_refunds_order "
        "ON refunds (order_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_refunds_order")
    op.execute("DROP INDEX IF EXISTS uq_refunds_provider_refund")
    op.execute("DROP TABLE IF EXISTS refunds")

    op.execute("DROP INDEX IF EXISTS uq_course_entitlements_active")
    op.execute("DROP INDEX IF EXISTS ix_course_entitlements_user")
    op.execute("DROP TABLE IF EXISTS course_entitlements")

    op.execute("DROP INDEX IF EXISTS ix_payment_webhook_event_type")
    op.execute("DROP INDEX IF EXISTS uq_payment_webhook_provider_event")
    op.execute("DROP TABLE IF EXISTS payment_webhook_events")

    op.execute("DROP INDEX IF EXISTS uq_payment_attempts_provider_payment")
    op.execute("DROP INDEX IF EXISTS ix_payment_attempts_order")
    op.execute("DROP TABLE IF EXISTS payment_attempts")

    op.execute("DROP INDEX IF EXISTS ix_orders_status")
    op.execute("DROP INDEX IF EXISTS uq_orders_provider_order")
    op.execute("DROP INDEX IF EXISTS ix_orders_user_created")
    op.execute("DROP TABLE IF EXISTS orders")

    op.execute("DROP INDEX IF EXISTS ix_course_bundles_slug")
    op.execute("DROP TABLE IF EXISTS course_bundles")

    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS metadata")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS bullets")
