"""D9 / Pass 3g §E.1 — safety_incidents table.

The audit surface for every safety finding the SafetyGate primitive
fires. Per-finding granularity (one row per SafetyFinding, not per
SafetyVerdict) so the dashboards can filter by category + severity
without unpacking JSONB.

  • full_context_pointer joins back to agent_actions.id for full
    investigation. Not a hard FK because agent_actions retention
    may eventually outlive incident retention; SET NULL would
    require an FK and the FK would block the simpler app-side
    cleanup we want for now.

  • evidence_redacted is the matched text with the matched payload
    itself redacted (e.g. "[API_KEY: sk-ant-***]") — we want to
    preserve the *fact* that an API key was matched without storing
    the key itself in our incident DB. Pass 3g §E.1 footnote.

  • The unreviewed-high-severity partial index supports the admin
    "needs review" queue without scanning the full table.

Revision ID: 0058_safety_incidents
Revises: 0057_entitlement_tier
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0058_safety_incidents"
down_revision: str | None = "0057_entitlement_tier"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "safety_incidents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("agent_name", sa.Text(), nullable=True),
        sa.Column("request_id", UUID(as_uuid=True), nullable=True),
        # incident_type maps to SafetyFinding.category. Validated at
        # the schema level (backend/app/schemas/safety.py) — we do
        # NOT add a CHECK constraint because new categories should be
        # adjustable without a migration. The cost of that flexibility
        # is that a buggy writer could insert nonsense; the writer is
        # a single primitive we own, so the risk is low.
        sa.Column("incident_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("detector", sa.Text(), nullable=False),
        sa.Column("evidence_redacted", sa.Text(), nullable=True),
        sa.Column("full_context_pointer", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "notified_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("review_outcome", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "severity IN ('info','low','medium','high','critical')",
            name="safety_incidents_severity_chk",
        ),
        sa.CheckConstraint(
            "decision IN ('allow','redact','warn','block')",
            name="safety_incidents_decision_chk",
        ),
        sa.CheckConstraint(
            "review_outcome IS NULL OR review_outcome IN "
            "('false_positive','confirmed','needs_more_data')",
            name="safety_incidents_review_outcome_chk",
        ),
    )
    # Per-user incident timeline. Hot for the trace endpoint and the
    # "this user is being abusive" investigation flow.
    op.create_index(
        "idx_safety_incidents_user",
        "safety_incidents",
        ["user_id", "occurred_at"],
    )
    # Admin "needs review" queue: high+critical, not yet reviewed.
    # Partial keeps the index tiny (most incidents are low/medium and
    # never need review). Pass 3g §E.4.
    op.create_index(
        "idx_safety_incidents_unreviewed",
        "safety_incidents",
        ["severity", "occurred_at"],
        postgresql_where=sa.text(
            "reviewed_at IS NULL AND severity IN ('high','critical')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_safety_incidents_unreviewed",
        table_name="safety_incidents",
    )
    op.drop_index("idx_safety_incidents_user", table_name="safety_incidents")
    op.drop_table("safety_incidents")
