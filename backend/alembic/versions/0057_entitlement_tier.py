"""D9 / Pass 3f — entitlement tier infrastructure.

Closes Pass 2 H1 (agents are completely ungated by entitlements).
Three things land together because they're all read by the same
EntitlementContext computation path:

  1. course_entitlements gets a `tier` column (and `metadata` jsonb)
       Three legal values: 'free', 'standard', 'premium'. Only
       'standard' is shipped in v1; 'premium' is allowed by the CHECK
       so adding the SKU later is config, not migration. metadata
       JSONB is added to support the per-student overrides Pass 3f
       §F.3 (granted_via='comp') and §H.3 (cost_ceiling_inr_override)
       call out — neither is in the original 0047 schema.

  2. free_tier_grants
       Three grant types: signup_grace (24h after signup),
       placement_quiz_session (per-session), demo_chat (explicit demo
       flow). Pass 3f §C.1.

  3. agent_actions.cost_inr + mv_student_daily_cost
       The rollup view Pass 3f §D.1 specifies. Refreshes every 60s
       via a Celery beat job (wired in D9 application code, not
       migration). The cost_inr column on agent_actions is a deviation
       from the 0001 schema — Pass 3f §D.2 says "each agent run
       writes its cost to agent_actions.cost_inr" but no prior
       migration adds it. Adding it here so the view's SUM clause
       has a real column to read.

Per-tier limits live in code (backend/app/core/tiers.py) not in the
DB. Tiers rarely change and PR-reviewed config beats a tiers table
that can drift between staging and prod.

Revision ID: 0057_entitlement_tier
Revises: 0056_curriculum_graph
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0057_entitlement_tier"
down_revision: str | None = "0056_curriculum_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── course_entitlements: tier + metadata ────────────────────────
    # tier: defaults to 'standard' so existing entitlements keep
    # working without backfill. The CHECK is permissive enough to
    # admit 'premium' without a future ALTER.
    op.execute(
        "ALTER TABLE course_entitlements "
        "ADD COLUMN tier TEXT NOT NULL DEFAULT 'standard' "
        "CHECK (tier IN ('free','standard','premium'))"
    )
    # metadata: required by Pass 3f §F.3 (granted_via='comp') and
    # §H.3 (cost_ceiling_inr_override). The 0047 table does not have
    # one, and the override mechanism stops working without it. JSONB
    # so the per-row overrides are queryable via -> / ->>.
    op.execute(
        "ALTER TABLE course_entitlements "
        "ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    # Hot path index on (user_id, tier) filtered to active rows. The
    # Layer 1 dependency does this lookup on every authenticated
    # agentic request — cannot afford a full scan.
    op.execute(
        "CREATE INDEX idx_entitlements_user_tier "
        "ON course_entitlements (user_id, tier) "
        "WHERE revoked_at IS NULL"
    )

    # ── free_tier_grants ────────────────────────────────────────────
    op.create_table(
        "free_tier_grants",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grant_type", sa.Text(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "grant_type IN ('signup_grace','placement_quiz_session','demo_chat')",
            name="free_tier_grants_type_chk",
        ),
    )
    # Hot path: "does user U have an active grant?" — index covers the
    # active filter (revoked_at IS NULL) and order by expires_at so
    # the lookup is constant-time per user.
    op.create_index(
        "idx_ftg_user_active",
        "free_tier_grants",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # ── agent_actions.cost_inr ──────────────────────────────────────
    # Deviation from D9 prompt's literal schema: Pass 3f §D names this
    # column but no prior migration adds it. The materialized view
    # below reads SUM(COALESCE(cost_inr,0)) — adding the column here
    # is the smallest change that makes the view valid SQL.
    # NUMERIC(12,4): up to ~99,999,999.9999 INR per row (impossibly
    # large, intentionally — never hit the limit) with 4 decimals
    # so sub-rupee per-call costs aren't lost to rounding.
    op.add_column(
        "agent_actions",
        sa.Column(
            "cost_inr",
            sa.Numeric(precision=12, scale=4),
            nullable=True,
        ),
    )

    # ── mv_student_daily_cost ───────────────────────────────────────
    # Per Pass 3f §D.1. Rolls up the last 7 days of agent_actions
    # cost into per-(student, day) totals. Refreshed every 60s via
    # Celery beat (the job is wired in D9 app code, not here).
    #
    # 7-day window because:
    #   - Cost ceiling check needs today only (1 day)
    #   - Operational dashboards want last-7-days trends (7 days)
    #   - Anything older is a weekly/monthly rollup; doesn't need
    #     to live in this view.
    #
    # CONCURRENTLY refresh requires a unique index, which we create
    # explicitly. Without it, the 60s refresh would lock writes on
    # the underlying table during refresh.
    op.execute(
        "CREATE MATERIALIZED VIEW mv_student_daily_cost AS "
        "SELECT "
        "    student_id AS user_id, "
        "    DATE(created_at AT TIME ZONE 'UTC') AS day_utc, "
        "    SUM(COALESCE(cost_inr, 0)) AS cost_inr_total, "
        "    COUNT(*) AS action_count "
        "FROM agent_actions "
        "WHERE created_at >= now() - interval '7 days' "
        "  AND student_id IS NOT NULL "
        "GROUP BY student_id, DATE(created_at AT TIME ZONE 'UTC') "
        "WITH NO DATA"
    )
    # Required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_sdc_user_day "
        "ON mv_student_daily_cost (user_id, day_utc)"
    )
    # First non-concurrent refresh to populate the view; subsequent
    # refreshes are concurrent (Celery beat job).
    op.execute("REFRESH MATERIALIZED VIEW mv_student_daily_cost")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_mv_sdc_user_day")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_student_daily_cost")
    op.drop_column("agent_actions", "cost_inr")

    op.drop_index("idx_ftg_user_active", table_name="free_tier_grants")
    op.drop_table("free_tier_grants")

    op.execute("DROP INDEX IF EXISTS idx_entitlements_user_tier")
    # ALTER ... DROP COLUMN is the cleanest reversal. The CHECK is
    # dropped automatically with the column.
    op.execute("ALTER TABLE course_entitlements DROP COLUMN IF EXISTS metadata")
    op.execute("ALTER TABLE course_entitlements DROP COLUMN IF EXISTS tier")
