"""D9 / Pass 3b — Supervisor v1 audit surface.

Closes the gap between the Supervisor design (Pass 3b §9.1, the trace
endpoint promise) and the existing 0054 / 0001 audit tables. Adds:

  • agent_actions.summary (Text, nullable)
        One-sentence summary of what an agent did. Pass 3b §3.1 names this
        as the field the Supervisor reads when it builds its
        AgentActionSummary list — pulling full output_data into every
        Supervisor turn would be expensive in tokens. The memory_curator
        pattern populates this on insert; pre-existing rows stay NULL
        and the Supervisor's prompt tolerates that.

  • idx_agent_call_chain_root_parent
        Composite index on (root_id, parent_id) for the trace endpoint
        (Pass 3i §F). The 0054 migration already has
        agent_call_chain_root_idx on (root_id, depth) which speeds up
        depth-ordered traversal; this second index speeds up the
        parent-pointer reconstruction the trace UI does when rendering
        the chain as a tree. NOTE: the D9 prompt named the columns
        `(request_id, parent_action_id)` but the actual schema columns
        from 0054 are `root_id` and `parent_id`. Using the real names.

  • idx_supervisor_declines (partial)
        Hot path: "show me every Supervisor decline in window X." The
        Supervisor writes its RouteDecision into
        agent_actions.output_data as JSONB; the partial index covers
        only rows where decline_reason is set, keeping the index small.
        This is the surface for the operational decline-reason
        dashboard (Pass 3i §G consumes this).

Revision ID: 0055_supervisor_v1
Revises: 0054_agentic_os_primitives
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_supervisor_v1"
down_revision: str | None = "0054_agentic_os_primitives"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── agent_actions.summary ───────────────────────────────────────
    # Nullable: existing rows have no summary, and writing one
    # retrospectively would require LLM calls we don't want to do at
    # migration time. The Supervisor's prompt is tolerant: rows where
    # summary IS NULL fall back to a tiny structural label
    # (agent_name + action_type) when rendered into AgentActionSummary.
    op.add_column(
        "agent_actions",
        sa.Column("summary", sa.Text(), nullable=True),
    )

    # ── agent_call_chain (root_id, parent_id) ───────────────────────
    # Reconstructing a chain as a tree means walking parent_id pointers
    # within a single root_id. Without this composite, the planner does
    # a sort on root_idx + filter on parent_id — adequate at low
    # volumes, but the trace endpoint reads recent chains for a single
    # student often enough to justify the second index.
    op.create_index(
        "idx_agent_call_chain_root_parent",
        "agent_call_chain",
        ["root_id", "parent_id"],
    )

    # ── idx_supervisor_declines (partial) ───────────────────────────
    # JSONB ->> returns text; the partial WHERE keeps the index off
    # 99% of agent_actions rows (specialists, not Supervisor declines).
    # Created via raw SQL because Alembic's create_index doesn't
    # speak JSONB expressions cleanly across versions.
    op.execute(
        "CREATE INDEX idx_supervisor_declines "
        "ON agent_actions (created_at DESC) "
        "WHERE agent_name = 'supervisor' "
        "AND output_data->>'decline_reason' IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_supervisor_declines")
    op.drop_index(
        "idx_agent_call_chain_root_parent",
        table_name="agent_call_chain",
    )
    op.drop_column("agent_actions", "summary")
