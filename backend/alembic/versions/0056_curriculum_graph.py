"""D9 / Pass 3e §B — curriculum knowledge graph schema.

Six tables. Empty until D15 populates them. Created in D9 so the
schema is in place when graph-aware tools are wired downstream.
Concepts are atomic curriculum units; relationships and resource
links are explicit; misconceptions are first-class entities;
candidate concepts go through admin review before promotion.

  concepts
  concept_relationships
  concept_resource_links
  misconceptions
  concept_candidates
  student_concept_engagement

Embedding dimension matches the agentic OS choice (1536) so a single
Voyage-3 / OpenAI text-embedding-3-small projection serves both
agent_memory and the curriculum graph. HNSW indexes on every
embedding column for cosine recall. pgvector is already enabled in
0054; this migration assumes that.

Why now (D9) vs. later (D15):
  Schema is small and load-bearing. Adding it later means D11/D12/D14
  agents that want graph reads have nothing to read against, OR they
  embed dialect-specific "table doesn't exist" fallbacks. The lazier
  path is to ship empty tables now and let queries return zero rows
  cleanly; D15's seeding job becomes an INSERT pass against fixed
  schema instead of "schema + seeding in the same deliverable."

Revision ID: 0056_curriculum_graph
Revises: 0055_supervisor_v1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0056_curriculum_graph"
down_revision: str | None = "0055_supervisor_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Same dim as agent_memory (see 0054). One projection serves both.
EMBEDDING_DIM = 1536


def upgrade() -> None:
    # ── concepts ────────────────────────────────────────────────────
    op.create_table(
        "concepts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        # canonical_explanation is the "best" 1-2 paragraph version
        # an agent can pull when explaining the concept. Stored
        # alongside description so authors can write both: a short
        # gloss (description) and a long-form teaching paragraph
        # (canonical_explanation). Both can be NULL during ingestion
        # of a candidate that hasn't been authored yet.
        sa.Column("canonical_explanation", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("difficulty_tier", sa.Integer(), nullable=False),
        sa.Column("typical_hours_to_master", sa.Float(), nullable=True),
        # placeholder; replaced with vector(1536) below
        sa.Column(
            "embedding",
            sa.dialects.postgresql.ARRAY(sa.Float),
            nullable=True,
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
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "difficulty_tier BETWEEN 1 AND 5",
            name="concepts_difficulty_tier_range",
        ),
    )
    # Same pgvector trick as 0054: drop the placeholder ARRAY column
    # and recreate as a real vector(N). SQLAlchemy Core has no
    # vector type; raw DDL is cleaner than registering a custom type
    # for a single migration.
    op.execute("ALTER TABLE concepts DROP COLUMN embedding")
    op.execute(f"ALTER TABLE concepts ADD COLUMN embedding vector({EMBEDDING_DIM})")

    op.create_index("idx_concepts_slug", "concepts", ["slug"])
    op.create_index("idx_concepts_domain", "concepts", ["domain"])
    op.execute(
        "CREATE INDEX idx_concepts_embedding "
        "ON concepts USING hnsw (embedding vector_cosine_ops)"
    )

    # ── concept_relationships ───────────────────────────────────────
    # Six relationship types (Pass 3e §B.2). Strength + confidence
    # are separate: strength is how strong the relationship is in the
    # curriculum (e.g. "absolutely must know A before B" = 1.0,
    # "helpful to know A before B" = 0.5); confidence is how sure we
    # are the relationship exists (e.g. manual entry = 1.0, LLM
    # inferred from one source = 0.7).
    op.create_table(
        "concept_relationships",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "from_concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column(
            "strength",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.8"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relationship_type IN ("
            "'prerequisite_of','builds_on','contrasts_with',"
            "'applies_to','specialization_of','co_occurs_with')",
            name="concept_relationships_type_chk",
        ),
        sa.CheckConstraint(
            "strength BETWEEN 0.0 AND 1.0",
            name="concept_relationships_strength_range",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0.0 AND 1.0",
            name="concept_relationships_confidence_range",
        ),
        sa.UniqueConstraint(
            "from_concept_id",
            "to_concept_id",
            "relationship_type",
            name="uq_concept_relationships_triple",
        ),
    )
    op.create_index(
        "idx_rel_from",
        "concept_relationships",
        ["from_concept_id", "relationship_type"],
    )
    op.create_index(
        "idx_rel_to",
        "concept_relationships",
        ["to_concept_id", "relationship_type"],
    )

    # ── concept_resource_links ──────────────────────────────────────
    # Maps concepts to the resources that teach them (lessons,
    # exercises, external videos, etc.). is_canonical marks the
    # single "best" resource per concept — agents that want to point
    # a student at a resource query WHERE is_canonical IS TRUE.
    # No DB-level constraint enforces "at most one canonical per
    # concept" because re-canonicalizing would require a transaction
    # that flips two rows; the application layer enforces uniqueness.
    op.create_table(
        "concept_resource_links",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resource_url", sa.Text(), nullable=True),
        sa.Column("resource_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "is_canonical",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "coverage",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'partial'"),
        ),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column(
            "embedding",
            sa.dialects.postgresql.ARRAY(sa.Float),
            nullable=True,
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
        sa.CheckConstraint(
            "resource_type IN ("
            "'lesson','lesson_resource','exercise',"
            "'external_video','external_repo','external_text')",
            name="concept_resource_links_type_chk",
        ),
        sa.CheckConstraint(
            "coverage IN ('intro','partial','full','advanced')",
            name="concept_resource_links_coverage_chk",
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR quality_score BETWEEN 0.0 AND 1.0",
            name="concept_resource_links_quality_range",
        ),
    )
    op.execute("ALTER TABLE concept_resource_links DROP COLUMN embedding")
    op.execute(
        f"ALTER TABLE concept_resource_links "
        f"ADD COLUMN embedding vector({EMBEDDING_DIM})"
    )
    op.create_index(
        "idx_crl_concept",
        "concept_resource_links",
        ["concept_id"],
    )
    op.create_index(
        "idx_crl_canonical",
        "concept_resource_links",
        ["concept_id"],
        postgresql_where=sa.text("is_canonical = TRUE"),
    )
    op.execute(
        "CREATE INDEX idx_crl_embedding "
        "ON concept_resource_links USING hnsw (embedding vector_cosine_ops)"
    )

    # ── misconceptions ──────────────────────────────────────────────
    # Pass 3e §B.4: misconceptions are first-class curriculum entities
    # (the false beliefs the curriculum corrects). Distinct from
    # student_misconceptions (Layer 1) which tracks which students
    # currently hold which misconceptions.
    op.create_table(
        "misconceptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "associated_concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "typical_symptoms",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column("correction_explanation", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            sa.dialects.postgresql.ARRAY(sa.Float),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute("ALTER TABLE misconceptions DROP COLUMN embedding")
    op.execute(
        f"ALTER TABLE misconceptions ADD COLUMN embedding vector({EMBEDDING_DIM})"
    )
    op.create_index(
        "idx_misconceptions_concept",
        "misconceptions",
        ["associated_concept_id"],
    )
    op.execute(
        "CREATE INDEX idx_misconceptions_embedding "
        "ON misconceptions USING hnsw (embedding vector_cosine_ops)"
    )

    # ── concept_candidates ──────────────────────────────────────────
    # Staging area for content_ingestion proposals. Pass 3e §C.2:
    # auto-creating concepts produces noise (synonym duplicates,
    # granularity drift, hallucinated concepts). Admin review keeps
    # the graph clean. status flows pending → approved/rejected/merged.
    op.create_table(
        "concept_candidates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("proposed_slug", sa.Text(), nullable=False),
        sa.Column("proposed_name", sa.Text(), nullable=False),
        sa.Column("proposed_description", sa.Text(), nullable=False),
        sa.Column("proposed_relationships", JSONB, nullable=True),
        sa.Column("source_resource_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_evidence", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "reviewed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "merged_into_concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','merged')",
            name="concept_candidates_status_chk",
        ),
    )
    # Hot path: admin pulling pending candidates ordered by confidence.
    op.create_index(
        "idx_concept_candidates_pending",
        "concept_candidates",
        ["confidence"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ── student_concept_engagement ──────────────────────────────────
    # Per-(user, concept) engagement metrics not covered by
    # user_skill_states (which is mastery only). Plateau is for
    # interrupt_agent risk-signaling: stuck for 7+ days at low mastery
    # is a strong intervention signal.
    op.create_table(
        "student_concept_engagement",
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
        sa.Column(
            "concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "minutes_engaged",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "last_engagement_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("breakthrough_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plateau_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "concept_id",
            name="uq_student_concept_engagement_pair",
        ),
    )
    op.create_index(
        "idx_sce_user",
        "student_concept_engagement",
        ["user_id"],
    )
    # Partial: interrupt_agent's "find plateaued students" query reads
    # only rows where plateau_at IS NOT NULL. Tiny index, big read.
    op.create_index(
        "idx_sce_plateau",
        "student_concept_engagement",
        ["plateau_at"],
        postgresql_where=sa.text("plateau_at IS NOT NULL"),
    )


def downgrade() -> None:
    # Reverse-order drop. Children first (FKs reference concepts).
    op.drop_index("idx_sce_plateau", table_name="student_concept_engagement")
    op.drop_index("idx_sce_user", table_name="student_concept_engagement")
    op.drop_table("student_concept_engagement")

    op.drop_index(
        "idx_concept_candidates_pending",
        table_name="concept_candidates",
    )
    op.drop_table("concept_candidates")

    op.execute("DROP INDEX IF EXISTS idx_misconceptions_embedding")
    op.drop_index("idx_misconceptions_concept", table_name="misconceptions")
    op.drop_table("misconceptions")

    op.execute("DROP INDEX IF EXISTS idx_crl_embedding")
    op.drop_index("idx_crl_canonical", table_name="concept_resource_links")
    op.drop_index("idx_crl_concept", table_name="concept_resource_links")
    op.drop_table("concept_resource_links")

    op.drop_index("idx_rel_to", table_name="concept_relationships")
    op.drop_index("idx_rel_from", table_name="concept_relationships")
    op.drop_table("concept_relationships")

    op.execute("DROP INDEX IF EXISTS idx_concepts_embedding")
    op.drop_index("idx_concepts_domain", table_name="concepts")
    op.drop_index("idx_concepts_slug", table_name="concepts")
    op.drop_table("concepts")
