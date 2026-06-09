"""Agentic OS — primitives layer.

Adds the seven tables that turn the existing 26-agent registry into a
production-grade agentic system without breaking a single existing
agent. Every primitive is opt-in via the ENABLE_* feature flags
(see app/core/config.py); this migration just creates the storage
substrate so the application code can lean on it.

Tables (one per primitive, plus per-primitive audit):

  agent_memory          — persistent long-term memory (pgvector + jsonb).
                          Hybrid recall: structured (key match) +
                          semantic (cosine similarity over embedding).
  agent_tool_calls      — full audit trail of every @tool execution
                          (args, result, status, duration, errors).
  agent_call_chain      — inter-agent invocation graph. `root_id`
                          ties an outermost execute() to every inner
                          call so traces are joinable. `depth` enforces
                          the agent_call_max_depth ceiling at write
                          time and reads tell us "how nested did this
                          go?". Cycle detection compares (caller,
                          callee) pairs along the chain.
  agent_evaluations     — every critic score (per attempt). Drives the
                          prompt-quality dashboard so we can spot
                          agents drifting below threshold over time.
  agent_escalations     — when retry budget exhausts, we land here.
                          Carries the best attempt + critic reasoning
                          + a flag for admin notification.
  agent_proactive_runs  — audit for cron- and webhook-triggered runs.
                          `idempotency_key` is UNIQUE so Celery retries
                          and GitHub redeliveries become no-op upserts.
  student_inbox         — proactive output destination. Cards
                          (nudges, celebrations, job briefs, review
                          due) the student sees in-app. Per-user partial
                          unique index on (user_id, idempotency_key)
                          stops double-posts on retry storms.

pgvector is enabled at the start; embedding column dimension is 1536
(OpenAI text-embedding-3-small / Voyage-3 padded). 1536 leaves the
provider door open at the cost of ~50% more bytes per row — cheap now,
re-embed-the-world expensive to undo.

Prod parity (Neon Postgres):
  • pgvector is available on every Neon plan (allowlisted); no special
    setup beyond the `CREATE EXTENSION` this migration runs.
  • The role that runs `alembic upgrade head` must have CREATE on the
    database. Neon's default project owner role does. If a
    least-privilege migration role is configured, ensure
    `GRANT CREATE ON DATABASE <db> TO <role>` is in place before
    deploying.

Dev parity (docker-compose):
  • The dev `db` service uses `pgvector/pgvector:pg16` (pinned to a
    digest in docker-compose.yml). The previous `postgres:16-alpine`
    omitted the extension binaries and could not run this migration.

Revision ID: 0054_agentic_os_primitives
Revises: 0053_student_messages
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

revision: str = "0054_agentic_os_primitives"
down_revision: str | None = "0053_student_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Embedding dimension is wired here so the upgrade and downgrade share
# one source of truth. If you ever switch providers and need to re-embed,
# change this in a follow-up migration that drops + recreates the column
# with the new dim — pgvector cannot ALTER a vector column's dimension.
EMBEDDING_DIM = 1536


def upgrade() -> None:
    # ── pgvector extension ──────────────────────────────────────────
    # IF NOT EXISTS so re-runs against a partially-migrated DB are
    # safe. Requires the postgres role to have CREATE on the database;
    # in dev that's the default `postgres` superuser, in Neon prod the
    # extension is pre-allowlisted.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── enums ───────────────────────────────────────────────────────
    # Three scopes only — keep this tight. Adding a new scope means a
    # new enum value via ALTER TYPE in a follow-up migration; resist
    # the temptation to overload `value` with another scope-like field.
    #
    # Created via raw SQL (not sa.Enum.create) because SQLAlchemy's
    # Postgres ENUM helper calls `CREATE TYPE` unconditionally — even
    # when paired with `create_type=False` on the column declaration,
    # the column-level Enum() still emits its own CREATE TYPE during
    # op.create_table() and you get a DuplicateObjectError on the
    # second emission. Raw SQL with IF NOT EXISTS sidesteps the
    # ambiguity entirely.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agent_memory_scope') THEN "
        "CREATE TYPE agent_memory_scope AS ENUM ('user', 'agent', 'global'); "
        "END IF; "
        "END $$;"
    )

    # ── agent_memory ────────────────────────────────────────────────
    op.create_table(
        "agent_memory",
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
            nullable=True,
        ),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            # Use postgresql.ENUM (not sa.Enum) so create_type=False
            # actually suppresses the type creation during create_table.
            # The generic sa.Enum re-emits CREATE TYPE on every column
            # decl regardless of the flag — that's the bug we hit before.
            ENUM(
                "user",
                "agent",
                "global",
                name="agent_memory_scope",
                create_type=False,
            ),
            nullable=False,
            server_default="user",
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        # Embedding lives in pgvector. NULL is allowed so structured-only
        # writes (no embedding model available, e.g. dev fallback) still
        # land — the recall layer falls back to key match in that case.
        sa.Column(
            "embedding",
            sa.dialects.postgresql.ARRAY(sa.Float),  # placeholder, replaced below
            nullable=True,
        ),
        sa.Column(
            "valence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column("source_message_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "access_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("valence BETWEEN -1.0 AND 1.0", name="agent_memory_valence_range"),
        sa.CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="agent_memory_confidence_range"),
    )
    # SQLAlchemy Core doesn't know about pgvector's vector type yet, so
    # the ARRAY placeholder above is replaced with the real vector(N)
    # column via raw DDL. Cleaner than registering a custom type for a
    # one-shot migration.
    op.execute("ALTER TABLE agent_memory DROP COLUMN embedding")
    op.execute(
        f"ALTER TABLE agent_memory ADD COLUMN embedding vector({EMBEDDING_DIM})"
    )

    # Hot-path indexes:
    #   • user+scope: structured recall ("everything memory_store knows
    #     about user X") — most common query
    #   • agent_name: per-agent introspection in admin
    #   • expires_at partial: the nightly decay sweep
    #   • HNSW on embedding: cosine similarity for semantic recall
    op.create_index(
        "agent_memory_user_scope_idx",
        "agent_memory",
        ["user_id", "scope"],
    )
    op.create_index(
        "agent_memory_agent_idx",
        "agent_memory",
        ["agent_name"],
    )
    op.create_index(
        "agent_memory_expires_idx",
        "agent_memory",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.execute(
        "CREATE INDEX agent_memory_embedding_idx "
        "ON agent_memory USING hnsw (embedding vector_cosine_ops)"
    )

    # ── agent_tool_calls ────────────────────────────────────────────
    op.create_table(
        "agent_tool_calls",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("args", JSONB, nullable=False),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Joins to agent_call_chain.root_id (loosely — tool calls don't
        # need their own depth column; we already store agent_name).
        sa.Column("call_chain_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok','error','timeout')",
            name="agent_tool_calls_status_chk",
        ),
    )
    op.create_index(
        "agent_tool_calls_agent_idx",
        "agent_tool_calls",
        ["agent_name", "created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "agent_tool_calls_user_idx",
        "agent_tool_calls",
        ["user_id", "created_at"],
    )
    op.create_index(
        "agent_tool_calls_chain_idx",
        "agent_tool_calls",
        ["call_chain_id"],
    )

    # ── agent_call_chain ────────────────────────────────────────────
    op.create_table(
        "agent_call_chain",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Same UUID across every link in a single outermost execute().
        # Lets you `WHERE root_id = '…'` to recover the full graph.
        sa.Column("root_id", UUID(as_uuid=True), nullable=False),
        # NULL when the link is a root call (caller is MOA / chat).
        sa.Column("parent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("caller_agent", sa.Text(), nullable=True),
        sa.Column("callee_agent", sa.Text(), nullable=False),
        sa.Column(
            "depth",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok','error','cycle','depth_exceeded')",
            name="agent_call_chain_status_chk",
        ),
        sa.CheckConstraint("depth >= 0", name="agent_call_chain_depth_nonneg"),
    )
    op.create_index(
        "agent_call_chain_root_idx",
        "agent_call_chain",
        ["root_id", "depth"],
    )
    op.create_index(
        "agent_call_chain_callee_idx",
        "agent_call_chain",
        ["callee_agent", "created_at"],
    )

    # ── agent_evaluations ───────────────────────────────────────────
    op.create_table(
        "agent_evaluations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("call_chain_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("accuracy_score", sa.Float(), nullable=True),
        sa.Column("helpful_score", sa.Float(), nullable=True),
        sa.Column("complete_score", sa.Float(), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("critic_reasoning", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_score BETWEEN 0.0 AND 1.0",
            name="agent_evaluations_total_range",
        ),
        sa.CheckConstraint("attempt_number >= 1", name="agent_evaluations_attempt_pos"),
    )
    op.create_index(
        "agent_evaluations_agent_idx",
        "agent_evaluations",
        ["agent_name", "created_at"],
    )

    # ── agent_escalations ───────────────────────────────────────────
    op.create_table(
        "agent_escalations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("call_chain_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("best_attempt", JSONB, nullable=True),
        sa.Column(
            "notified_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "agent_escalations_agent_idx",
        "agent_escalations",
        ["agent_name", "created_at"],
    )

    # ── agent_proactive_runs ────────────────────────────────────────
    op.create_table(
        "agent_proactive_runs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_name", sa.Text(), nullable=False),
        # 'cron' | 'webhook:github' | 'webhook:stripe' | 'webhook:custom'
        sa.Column("trigger_source", sa.Text(), nullable=False),
        sa.Column("trigger_key", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Idempotency:
        #   • cron: f"{agent}:{cron_expr}:{date_bucket}" so a Celery
        #     retry of the same task on the same day is a no-op.
        #   • webhook: provider-specific delivery ID (e.g. GitHub's
        #     X-GitHub-Delivery header) so re-deliveries don't re-fire.
        # NULL is allowed for legacy/uninstrumented call sites; UNIQUE
        # only fires on non-NULL values via the index below.
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued','ok','error','skipped')",
            name="agent_proactive_runs_status_chk",
        ),
    )
    op.create_index(
        "agent_proactive_runs_user_idx",
        "agent_proactive_runs",
        ["user_id", "created_at"],
    )
    # Partial unique — NULL idempotency keys do not collide. This is the
    # safety net that turns a Celery double-fire into a single row.
    op.create_index(
        "agent_proactive_runs_idemp_uidx",
        "agent_proactive_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # ── student_inbox ───────────────────────────────────────────────
    op.create_table(
        "student_inbox",
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
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("cta_label", sa.Text(), nullable=True),
        sa.Column("cta_url", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Per-user idempotency, scoped by the calling agent. A nudge
        # fired twice for the same student in the same window collapses
        # to one row instead of three. NULL = no idempotency requested,
        # which is fine for one-off cards.
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Hot path: "what unread cards does this user have?" — the inbox
    # query the frontend will hammer.
    op.create_index(
        "student_inbox_user_unread_idx",
        "student_inbox",
        ["user_id", "read_at", "created_at"],
    )
    # Partial unique on (user_id, idempotency_key). NULL keys never
    # collide; a same-key second write becomes a 23505 we can catch
    # and turn into an upsert in the application layer.
    op.create_index(
        "student_inbox_idemp_uidx",
        "student_inbox",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    # Reverse-order drop. The pgvector extension is left installed
    # because other future migrations may use it; if you really need to
    # purge it, do so manually with `DROP EXTENSION vector` after this
    # downgrade — we do not gate it here since extension drops can
    # cascade unexpectedly.
    op.drop_index("student_inbox_idemp_uidx", table_name="student_inbox")
    op.drop_index("student_inbox_user_unread_idx", table_name="student_inbox")
    op.drop_table("student_inbox")

    op.drop_index(
        "agent_proactive_runs_idemp_uidx",
        table_name="agent_proactive_runs",
    )
    op.drop_index(
        "agent_proactive_runs_user_idx",
        table_name="agent_proactive_runs",
    )
    op.drop_table("agent_proactive_runs")

    op.drop_index("agent_escalations_agent_idx", table_name="agent_escalations")
    op.drop_table("agent_escalations")

    op.drop_index("agent_evaluations_agent_idx", table_name="agent_evaluations")
    op.drop_table("agent_evaluations")

    op.drop_index("agent_call_chain_callee_idx", table_name="agent_call_chain")
    op.drop_index("agent_call_chain_root_idx", table_name="agent_call_chain")
    op.drop_table("agent_call_chain")

    op.drop_index("agent_tool_calls_chain_idx", table_name="agent_tool_calls")
    op.drop_index("agent_tool_calls_user_idx", table_name="agent_tool_calls")
    op.drop_index("agent_tool_calls_agent_idx", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")

    op.execute("DROP INDEX IF EXISTS agent_memory_embedding_idx")
    op.drop_index("agent_memory_expires_idx", table_name="agent_memory")
    op.drop_index("agent_memory_agent_idx", table_name="agent_memory")
    op.drop_index("agent_memory_user_scope_idx", table_name="agent_memory")
    op.drop_table("agent_memory")

    op.execute("DROP TYPE IF EXISTS agent_memory_scope")
