"""agent_invocation_log — unified per-LLM-call cost log + backfill from
``generation_logs`` and ``mock_cost_log``.

This migration creates the ``agent_invocation_log`` table and backfills it
from the two existing per-agent cost tables. After this migration:

* New agents (readiness diagnostic, JD decoder) write here exclusively.
* Resume agent and mock interview agent **dual-write**: legacy table + this
  one. Their existing read paths (e.g. ``quota_service._count_events``)
  continue to read from the legacy tables until a parallel-read verification
  gate has passed for 100 consecutive checks.

**Historical backfill caveat — IMPORTANT for any analyst querying this table:**
``generation_logs`` rows do not record per-sub-agent breakdowns; the resume
pipeline previously logged *one* cost-bearing event per generation. We
backfill those rows with the synthetic label ``sub_agent='tailoring_agent'``.
Consequently, **per-sub-agent observability for ``source='resume_generation'``
begins from 2026-04-25 (this migration's deploy date)** — earlier rows are
backfilled with the catch-all label and should be excluded from sub-agent
breakdown analytics. ``mock_cost_log`` already had per-sub-agent rows so its
backfill is faithful.

**Sunset target for the dual-write window: 2026-05-09** (~2 weeks). After
the read-path flip, a follow-up migration drops the cost columns on
``generation_logs`` and the ``mock_cost_log`` table itself.

Revision ID: 0040_agent_invocation_log
Revises: 0039_admin_console_v1
Create Date: 2026-04-25
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0040_agent_invocation_log"
down_revision: str | None = "0039_admin_console_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # migration_gates — a small KV table that records the state of in-flight
    # data migrations. Used here for the dual-write parallel-read gate:
    # quota_service compares legacy and new counts on every read; on each
    # agreement we increment 'agent_invocation_log_quota_parity'; once the
    # counter reaches AGREEMENT_THRESHOLD (=100) the gate flips and the
    # service starts reading from the new table.
    #
    # The table is intentionally generic so future migrations (post-flip
    # cleanup, mock_cost_log read-path flip, etc.) can use the same
    # primitive.
    # ------------------------------------------------------------------
    op.create_table(
        "migration_gates",
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column(
            "consecutive_agreements",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_checks",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_divergences",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "flipped",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "last_divergence_payload",
            sa.JSON,
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.bulk_insert(
        sa.table(
            "migration_gates",
            sa.column("name", sa.String),
            sa.column("consecutive_agreements", sa.Integer),
            sa.column("total_checks", sa.Integer),
            sa.column("total_divergences", sa.Integer),
            sa.column("flipped", sa.Boolean),
        ),
        [
            {
                "name": "agent_invocation_log_quota_parity",
                "consecutive_agreements": 0,
                "total_checks": 0,
                "total_divergences": 0,
                "flipped": False,
            }
        ],
    )

    op.create_table(
        "agent_invocation_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("sub_agent", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column(
            "tokens_in", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "tokens_out", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "cost_inr", sa.Float, nullable=False, server_default="0.0"
        ),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_invocation_log_user_id",
        "agent_invocation_log",
        ["user_id"],
    )
    op.create_index(
        "ix_agent_invocation_log_user_source",
        "agent_invocation_log",
        ["user_id", "source"],
    )
    op.create_index(
        "ix_agent_invocation_log_source_id",
        "agent_invocation_log",
        ["source", "source_id"],
    )
    op.create_index(
        "ix_agent_invocation_log_created_at",
        "agent_invocation_log",
        ["created_at"],
    )

    # ------------------------------------------------------------------
    # Backfill from the two legacy tables. UUIDs are generated in Python
    # rather than via gen_random_uuid() so the migration runs unchanged on
    # SQLite (test) and Postgres (prod). Casts are written to work on both:
    # SQLite stores UUIDs as text already, so the ::text cast is a no-op
    # there; Postgres requires it.
    #
    # Maps the legacy generation_logs.event field to the new status:
    #   completed -> succeeded
    #   failed    -> failed
    # The lifecycle-only events (started, quota_blocked, downloaded) are
    # NOT backfilled — they are not cost-bearing.
    #
    # generation_logs sub_agent is set to the synthetic catch-all
    # 'tailoring_agent' because the legacy schema did not record per-sub-
    # agent breakdowns. See the module docstring for the analytics caveat.
    #
    # mock_cost_log already stored per-sub-agent rows so its backfill is
    # faithful. Status is 'succeeded' for all legacy mock rows because the
    # old code only persisted a row on a successful LLM call.
    # ------------------------------------------------------------------
    bind = op.get_bind()

    gen_rows = bind.execute(
        sa.text(
            """
            SELECT
                user_id,
                tailored_resume_id,
                event,
                model,
                input_tokens,
                output_tokens,
                cost_inr,
                latency_ms,
                error_message,
                created_at
            FROM generation_logs
            WHERE event IN ('completed', 'failed')
            """
        )
    ).fetchall()

    invocation_table = sa.table(
        "agent_invocation_log",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("source", sa.String),
        sa.column("source_id", sa.String),
        sa.column("sub_agent", sa.String),
        sa.column("model", sa.String),
        sa.column("tokens_in", sa.Integer),
        sa.column("tokens_out", sa.Integer),
        sa.column("cost_inr", sa.Float),
        sa.column("latency_ms", sa.Integer),
        sa.column("status", sa.String),
        sa.column("error_message", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    event_to_status = {"completed": "succeeded", "failed": "failed"}
    resume_payload = [
        {
            "id": uuid.uuid4(),
            "user_id": row.user_id,
            "source": "resume_generation",
            "source_id": str(row.tailored_resume_id) if row.tailored_resume_id else None,
            "sub_agent": "tailoring_agent",
            "model": row.model or "unknown",
            "tokens_in": int(row.input_tokens or 0),
            "tokens_out": int(row.output_tokens or 0),
            "cost_inr": float(row.cost_inr or 0.0),
            "latency_ms": row.latency_ms,
            "status": event_to_status[row.event],
            "error_message": row.error_message,
            "created_at": row.created_at,
        }
        for row in gen_rows
    ]
    if resume_payload:
        op.bulk_insert(invocation_table, resume_payload)

    mock_rows = bind.execute(
        sa.text(
            """
            SELECT
                isess.user_id           AS user_id,
                mcl.session_id          AS session_id,
                mcl.sub_agent           AS sub_agent,
                mcl.model               AS model,
                mcl.input_tokens        AS input_tokens,
                mcl.output_tokens       AS output_tokens,
                mcl.cost_inr            AS cost_inr,
                mcl.latency_ms          AS latency_ms,
                mcl.created_at          AS created_at
            FROM mock_cost_log mcl
            JOIN interview_sessions isess ON isess.id = mcl.session_id
            """
        )
    ).fetchall()

    mock_payload = [
        {
            "id": uuid.uuid4(),
            "user_id": row.user_id,
            "source": "mock_session",
            "source_id": str(row.session_id),
            "sub_agent": row.sub_agent,
            "model": row.model,
            "tokens_in": int(row.input_tokens or 0),
            "tokens_out": int(row.output_tokens or 0),
            "cost_inr": float(row.cost_inr or 0.0),
            "latency_ms": row.latency_ms,
            "status": "succeeded",
            "error_message": None,
            "created_at": row.created_at,
        }
        for row in mock_rows
    ]
    if mock_payload:
        op.bulk_insert(invocation_table, mock_payload)


def downgrade() -> None:
    op.drop_index(
        "ix_agent_invocation_log_created_at", table_name="agent_invocation_log"
    )
    op.drop_index(
        "ix_agent_invocation_log_source_id", table_name="agent_invocation_log"
    )
    op.drop_index(
        "ix_agent_invocation_log_user_source", table_name="agent_invocation_log"
    )
    op.drop_index(
        "ix_agent_invocation_log_user_id", table_name="agent_invocation_log"
    )
    op.drop_table("agent_invocation_log")
    op.drop_table("migration_gates")
