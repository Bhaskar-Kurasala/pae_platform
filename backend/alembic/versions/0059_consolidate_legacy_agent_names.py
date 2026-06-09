"""D11 / Pass 3c E2 — consolidate legacy agent_name to senior_engineer.

D11 merged code_review + coding_assistant + senior_engineer (legacy)
into the unified senior_engineer (AgenticBaseAgent) at the cutover
commit (115921f). Historical agent_actions rows have
agent_name='code_review' or 'coding_assistant' from before the
migration. Without this consolidation, services that aggregate by
agent_name (at_risk_student_service, confusion_heatmap_service,
intent_before_debug_service, admin route's _AGENT_VERBS lookup)
would silently miss historical activity after the cutover renamed
those string references to 'senior_engineer'.

Updates only the agent_actions table; no schema change.

Downgrade is intentionally a no-op — restoring the historical
distinction between the three legacy paths from operational data
isn't reliably possible (the original agent_name was the only
distinguishing field; no separate column captured "which sub-mode
of code review fired"). Restore from a pre-migration database
backup if rollback is needed.

Revision ID: 0059_consolidate_legacy_agent_names
Revises: 0058_safety_incidents
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059_consolidate_legacy_agents"
down_revision: str | None = "0058_safety_incidents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE agent_actions
        SET agent_name = 'senior_engineer'
        WHERE agent_name IN ('code_review', 'coding_assistant')
        """
    )


def downgrade() -> None:
    # Restoring the historical distinction between code_review,
    # coding_assistant, and senior_engineer (legacy) isn't possible
    # from operational data — the agent_name was the only column
    # that captured which sub-mode fired. If rollback is needed,
    # restore from a pre-migration backup.
    pass
