"""readiness workspace — persist autopsies, kits, action completions, click telemetry

Adds four additive tables that close the gaps in the Job Readiness page:

  * portfolio_autopsy_results — autopsy POSTs were ungraded; now persisted
  * application_kits         — kit export was a fake setInterval; now real
  * readiness_action_completions — Overview "top-3 next actions" need a
                                   memory of what the user already cleared
  * readiness_workspace_events    — per-user click + view telemetry across
                                    the workspace (Overview/Resume/JD/...)

Strictly additive — no destructive operations. Defaults chosen so reruns
are no-ops on existing rows. Uses `IF NOT EXISTS` on every CREATE so the
migration is safe across branches that may have added one of these tables
already.

Revision ID: 0046_readiness_workspace
Revises: 0045_notebook_graduation
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0046_readiness_workspace"
down_revision: str | None = "0045_notebook_graduation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- portfolio_autopsy_results ----------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_autopsy_results (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            project_title VARCHAR(200) NOT NULL,
            project_description TEXT NOT NULL,
            code TEXT NULL,
            headline TEXT NOT NULL,
            overall_score INTEGER NOT NULL,
            axes JSON NOT NULL,
            what_worked JSON NOT NULL DEFAULT '[]',
            what_to_do_differently JSON NOT NULL DEFAULT '[]',
            production_gaps JSON NOT NULL DEFAULT '[]',
            next_project_seed TEXT NULL,
            raw_request JSON NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portfolio_autopsy_user_created "
        "ON portfolio_autopsy_results (user_id, created_at DESC)"
    )

    # --- application_kits -------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS application_kits (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            label VARCHAR(120) NOT NULL,
            target_role VARCHAR(120) NULL,
            base_resume_id UUID NULL REFERENCES resumes(id) ON DELETE SET NULL,
            tailored_resume_id UUID NULL REFERENCES tailored_resumes(id) ON DELETE SET NULL,
            jd_library_id UUID NULL REFERENCES jd_library(id) ON DELETE SET NULL,
            mock_session_id UUID NULL REFERENCES interview_sessions(id) ON DELETE SET NULL,
            autopsy_id UUID NULL REFERENCES portfolio_autopsy_results(id) ON DELETE SET NULL,
            manifest JSON NOT NULL DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'building',
            pdf_blob BYTEA NULL,
            generated_at TIMESTAMP WITH TIME ZONE NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_application_kits_user_created "
        "ON application_kits (user_id, created_at DESC)"
    )

    # --- readiness_action_completions ------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS readiness_action_completions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action_kind VARCHAR(40) NOT NULL,
            payload_hash VARCHAR(64) NOT NULL,
            payload JSON NULL,
            completed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_readiness_action_completion "
        "ON readiness_action_completions (user_id, action_kind, payload_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_readiness_action_completions_user_completed "
        "ON readiness_action_completions (user_id, completed_at DESC)"
    )

    # --- readiness_workspace_events --------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS readiness_workspace_events (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            view VARCHAR(32) NOT NULL,
            event VARCHAR(64) NOT NULL,
            payload JSON NULL,
            session_id UUID NULL REFERENCES readiness_diagnostic_sessions(id) ON DELETE SET NULL,
            occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_readiness_workspace_events_user_occurred "
        "ON readiness_workspace_events (user_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_readiness_workspace_events_view_event "
        "ON readiness_workspace_events (view, event)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_readiness_workspace_events_view_event")
    op.execute("DROP INDEX IF EXISTS ix_readiness_workspace_events_user_occurred")
    op.execute("DROP TABLE IF EXISTS readiness_workspace_events")

    op.execute("DROP INDEX IF EXISTS ix_readiness_action_completions_user_completed")
    op.execute("DROP INDEX IF EXISTS uq_readiness_action_completion")
    op.execute("DROP TABLE IF EXISTS readiness_action_completions")

    op.execute("DROP INDEX IF EXISTS ix_application_kits_user_created")
    op.execute("DROP TABLE IF EXISTS application_kits")

    op.execute("DROP INDEX IF EXISTS ix_portfolio_autopsy_user_created")
    op.execute("DROP TABLE IF EXISTS portfolio_autopsy_results")
