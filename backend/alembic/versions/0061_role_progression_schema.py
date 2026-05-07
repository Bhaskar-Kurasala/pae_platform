"""D15 CP1 — role progression schema + seed.

Architectural reframe: AICareerOS is a curated linear career simulation
where students progress through six role identities — python_developer →
data_analyst → data_scientist → ml_engineer → genai_engineer →
senior_genai_engineer. Each non-terminal role is gated by a capstone
(project_evaluator) + mock interview (mock_interview).

This migration ships the storage substrate and the founder-authored seed
data (role identity statements + first-pass gate thresholds). Existing
agents will read from these tables in CP3-CP4 to adjust voice and ground
recommendations in the student's current role.

Three tables:

  roles                 — six role identities, ordered. `slug` is the
                          stable agent-facing key; `description` is the
                          identity statement (who the student IS in this
                          role, not what they study). Content is
                          discovered at runtime per D-E.
  role_transitions      — five gate definitions, one per adjacent pair.
                          `mock_interview_dimensions` is a JSONB rubric
                          mapping dimension_name → weight (sums to 1.0).
                          Thresholds are first-pass and admin-tunable
                          via direct DB updates per D-B.
  student_role_state    — one row per student (UNIQUE on student_id).
                          `current_role_id` is the load-bearing field
                          read by every prompt-update agent.
                          `transitions_completed` is an append-only JSONB
                          array of {from_slug, to_slug, completed_at,
                          capstone_score, mock_session_ids}.
                          `gates_attempted` is JSONB scratch space for
                          attempt-level history.

Seed data is co-shipped here (six roles + five transitions) because
the schema's meaning IS the seeded identity rows — empty roles + empty
transitions is not a valid state for the platform. The student
backfill (existing users → python_developer) ships as a separate
migration (0062) per Pattern 3 (data migrations ship in their own
commit so rollback discipline is clean).

Revision ID: 0061_role_progression_schema
Revises: 0060_goal_contracts_schema_fix
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0061_role_progression_schema"
down_revision: str | None = "0060_goal_contracts_schema_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ── Founder-authored role identity statements ──────────────────────────
# 2-4 sentences each. Captures role IDENTITY (who the student is when
# they're in this role), not role CONTENT (what they study). Content is
# discovered at runtime per D-E. Verbatim from D15 prompt body.
ROLE_SEEDS: list[dict] = [
    {
        "slug": "python_developer",
        "display_name": "Python Developer",
        "sequence_order": 1,
        "is_terminal": False,
        "description": (
            "You are a Python Developer on AICareerOS. This role builds "
            "the foundation every later role depends on — Python "
            "competence as a working engineer, not as a learner. Your "
            "job is to become someone who can write, run, debug, and "
            "maintain Python without supervision. When you can do that "
            "reliably, you're ready to use Python as a tool for working "
            "with data."
        ),
    },
    {
        "slug": "data_analyst",
        "display_name": "Data Analyst",
        "sequence_order": 2,
        "is_terminal": False,
        "description": (
            "You are a Data Analyst on AICareerOS. This is where Python "
            "becomes a tool for understanding data — pandas, SQL, "
            "exploratory analysis, honest visualization. Your job is to "
            "take messy data and produce honest answers: you understand "
            "what the data shows, you understand what it doesn't show, "
            "and you can explain both clearly."
        ),
    },
    {
        "slug": "data_scientist",
        "display_name": "Data Scientist",
        "sequence_order": 3,
        "is_terminal": False,
        "description": (
            "You are a Data Scientist on AICareerOS. This is where "
            "uncertainty becomes a first-class concept — statistics, "
            "hypothesis testing, predictive modeling, evaluation "
            "discipline. Your job is to move from 'what happened' to "
            "'what's likely to happen, and how confident are we' — with "
            "the rigor to be honest about what you don't know."
        ),
    },
    {
        "slug": "ml_engineer",
        "display_name": "ML Engineer",
        "sequence_order": 4,
        "is_terminal": False,
        "description": (
            "You are an ML Engineer on AICareerOS. This is where models "
            "become systems — deployment, training pipelines, serving "
            "infrastructure, monitoring. Your job is to make models work "
            "in production: they serve traffic, they don't fall over, "
            "they don't silently degrade, and someone other than you "
            "can operate them."
        ),
    },
    {
        "slug": "genai_engineer",
        "display_name": "GenAI Engineer",
        "sequence_order": 5,
        "is_terminal": False,
        "description": (
            "You are a GenAI Engineer on AICareerOS. This is where you "
            "build applications on language models that survive "
            "production reality — RAG systems, evaluation harnesses, "
            "prompt engineering with measurement, cost engineering. "
            "Your job is to design LLM-powered systems that actually "
            "work, not demos that fall over the moment a user asks "
            "something unexpected."
        ),
    },
    {
        "slug": "senior_genai_engineer",
        "display_name": "Senior GenAI Engineer",
        "sequence_order": 6,
        "is_terminal": True,
        "description": (
            "You are a Senior GenAI Engineer on AICareerOS — the "
            "terminal role on the platform. Your job at this level is "
            "no longer to build the system; it's to decide what system "
            "gets built and why. You make architecture choices, set "
            "evaluation discipline, own the trade-offs that don't have "
            "right answers — only better-justified answers. When you "
            "pass this role's gate AND the founder's in-person "
            "interview, the platform endorses external Senior GenAI "
            "Engineer applications."
        ),
    },
]


# ── Standard mock_interview_dimensions for all transitions ─────────────
# Uniform across all transitions in v1; weights sum to 1.0. Future
# iteration may shift weights per transition; first-pass uniformity
# simplifies CP1 reasoning and gate-evaluation logic.
MOCK_INTERVIEW_DIMENSIONS = {
    "clarity_of_questioning": 0.20,
    "directional_adherence": 0.30,
    "complexity_adaptation": 0.25,
    "technical_correctness": 0.25,
}


# ── Founder-authored gate thresholds (first-pass, admin-tunable) ───────
# Thresholds tighten across the progression, mirroring the founder's
# in-person interview standard at the senior_genai_engineer transition.
# senior_genai_engineer is the only gate requiring two capstones — it
# reflects the product opinion that the final transition demands
# demonstrated pattern, not single performance.
TRANSITION_SEEDS: list[dict] = [
    {
        "from_slug": "python_developer",
        "to_slug": "data_analyst",
        "capstone_threshold": 0.65,
        "capstone_count_required": 1,
        "mock_interview_pass_threshold": 0.65,
    },
    {
        "from_slug": "data_analyst",
        "to_slug": "data_scientist",
        "capstone_threshold": 0.70,
        "capstone_count_required": 1,
        "mock_interview_pass_threshold": 0.70,
    },
    {
        "from_slug": "data_scientist",
        "to_slug": "ml_engineer",
        "capstone_threshold": 0.72,
        "capstone_count_required": 1,
        "mock_interview_pass_threshold": 0.72,
    },
    {
        "from_slug": "ml_engineer",
        "to_slug": "genai_engineer",
        "capstone_threshold": 0.75,
        "capstone_count_required": 1,
        "mock_interview_pass_threshold": 0.75,
    },
    {
        "from_slug": "genai_engineer",
        "to_slug": "senior_genai_engineer",
        "capstone_threshold": 0.80,
        "capstone_count_required": 2,
        "mock_interview_pass_threshold": 0.80,
    },
]


def upgrade() -> None:
    # ── roles ───────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sequence_order", sa.Integer(), nullable=False),
        sa.Column(
            "is_terminal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="roles_slug_key"),
        sa.UniqueConstraint("sequence_order", name="roles_sequence_order_key"),
        sa.CheckConstraint("sequence_order >= 1", name="roles_sequence_order_pos"),
    )
    # slug is the agent-facing stable key; sequence_order drives "next
    # role" lookups in evaluate_student_against_gate. Both are unique
    # constraints above; the indexes are redundant on Postgres (UNIQUE
    # implies a btree) but keeping them explicit matches the prompt spec
    # and serves as documentation for future readers.
    op.create_index("roles_slug_idx", "roles", ["slug"])
    op.create_index("roles_sequence_order_idx", "roles", ["sequence_order"])

    # ── role_transitions ────────────────────────────────────────────
    op.create_table(
        "role_transitions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "from_role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "to_role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("capstone_threshold", sa.Float(), nullable=False),
        sa.Column(
            "capstone_count_required",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        # JSONB rubric: dimension_name → weight. Weights MUST sum to 1.0;
        # gate-evaluation logic asserts this at read time. Stored as
        # JSONB (not a per-dimension table) because dimensions are
        # admin-tunable + per-transition and a relational shape would
        # over-engineer for v1.
        sa.Column("mock_interview_dimensions", JSONB, nullable=False),
        sa.Column("mock_interview_pass_threshold", sa.Float(), nullable=False),
        sa.Column(
            "mock_interview_sessions_required_pass",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
        sa.Column(
            "mock_interview_sessions_window",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column(
            "additional_gate_logic",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("from_role_id", "to_role_id", name="role_transitions_pair_key"),
        sa.CheckConstraint(
            "capstone_threshold BETWEEN 0.0 AND 1.0",
            name="role_transitions_capstone_threshold_range",
        ),
        sa.CheckConstraint(
            "mock_interview_pass_threshold BETWEEN 0.0 AND 1.0",
            name="role_transitions_mock_threshold_range",
        ),
        sa.CheckConstraint(
            "capstone_count_required >= 1",
            name="role_transitions_capstone_count_pos",
        ),
        sa.CheckConstraint(
            "mock_interview_sessions_required_pass >= 1",
            name="role_transitions_mock_sessions_required_pos",
        ),
        sa.CheckConstraint(
            "mock_interview_sessions_window >= mock_interview_sessions_required_pass",
            name="role_transitions_window_gte_required",
        ),
        sa.CheckConstraint(
            "from_role_id <> to_role_id",
            name="role_transitions_no_self_loop",
        ),
    )
    op.create_index(
        "role_transitions_from_idx", "role_transitions", ["from_role_id"]
    )
    op.create_index(
        "role_transitions_to_idx", "role_transitions", ["to_role_id"]
    )

    # ── student_role_state ──────────────────────────────────────────
    op.create_table(
        "student_role_state",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "current_role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "role_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Append-only JSONB array of completion records:
        #   {from_slug, to_slug, completed_at, capstone_score, mock_session_ids}
        # Read at every CP3/CP4 prompt-update agent.
        sa.Column(
            "transitions_completed",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Scratch for attempt-level history; structure intentionally
        # loose at v1 since the consumer (evaluate_student_against_gate)
        # reads exercise_submissions + agent_actions for authoritative
        # state. This column is for admin observability + future UI.
        sa.Column(
            "gates_attempted",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("student_id", name="student_role_state_student_uniq"),
    )
    # The student_id UNIQUE constraint above already creates a unique
    # btree; redeclaring as a named index keeps the prompt's spec
    # explicit and gives admin queries a predictable name.
    op.create_index(
        "student_role_state_current_role_idx",
        "student_role_state",
        ["current_role_id"],
    )

    # ── Seed: six roles ─────────────────────────────────────────────
    # Insert via raw SQL with parameter binding rather than the table
    # object so this migration is self-contained (doesn't depend on
    # SQLAlchemy model definitions that may evolve).
    roles_table = sa.table(
        "roles",
        sa.column("slug", sa.Text),
        sa.column("display_name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("sequence_order", sa.Integer),
        sa.column("is_terminal", sa.Boolean),
    )
    op.bulk_insert(roles_table, ROLE_SEEDS)

    # ── Seed: five transitions ──────────────────────────────────────
    # Resolve role slugs → ids via INSERT ... SELECT so we don't need a
    # round-trip to fetch UUIDs. JSONB literal for dimensions encoded
    # as a Postgres JSON literal string.
    import json as _json

    dim_literal = _json.dumps(MOCK_INTERVIEW_DIMENSIONS)
    for transition in TRANSITION_SEEDS:
        op.execute(
            sa.text(
                """
                INSERT INTO role_transitions (
                    from_role_id,
                    to_role_id,
                    capstone_threshold,
                    capstone_count_required,
                    mock_interview_dimensions,
                    mock_interview_pass_threshold,
                    mock_interview_sessions_required_pass,
                    mock_interview_sessions_window
                )
                SELECT
                    f.id,
                    t.id,
                    :capstone_threshold,
                    :capstone_count_required,
                    CAST(:mock_dimensions AS JSONB),
                    :mock_pass_threshold,
                    2,
                    3
                FROM roles f, roles t
                WHERE f.slug = :from_slug AND t.slug = :to_slug
                """
            ).bindparams(
                from_slug=transition["from_slug"],
                to_slug=transition["to_slug"],
                capstone_threshold=transition["capstone_threshold"],
                capstone_count_required=transition["capstone_count_required"],
                mock_dimensions=dim_literal,
                mock_pass_threshold=transition["mock_interview_pass_threshold"],
            )
        )


def downgrade() -> None:
    op.drop_index(
        "student_role_state_current_role_idx", table_name="student_role_state"
    )
    op.drop_table("student_role_state")

    op.drop_index("role_transitions_to_idx", table_name="role_transitions")
    op.drop_index("role_transitions_from_idx", table_name="role_transitions")
    op.drop_table("role_transitions")

    op.drop_index("roles_sequence_order_idx", table_name="roles")
    op.drop_index("roles_slug_idx", table_name="roles")
    op.drop_table("roles")
