"""Lesson player: assets, prerequisites, granular progress

Adds the data spine for the course-locked notebook + video learning system:

  * lesson_assets        — multiple notebooks + a video + capstone brief per
                           lesson, replacing the single Lesson.video_url slot.
                           storage_ref is the opaque key (R2 object key for
                           notebooks, Mux playback_id for videos).
  * lesson_prerequisites — directed edges (lesson_id requires required_lesson_id).
                           A lesson is unlocked iff all required lessons are
                           complete for the student. Self-referential FK with
                           CASCADE so deleting a lesson removes its edges.
  * student_asset_progress — per-(student, asset) row tracking watch_pct,
                           executed_at, last_position_s. The lesson-level
                           StudentProgress.completed_at is derived from this
                           plus the lesson's completion_policy.
  * lessons.completion_policy — JSON column for the per-lesson rule
                           ({"video_min_watch_pct": 0.9,
                             "require_all_practice_runs": true,
                             "require_capstone_submitted": false}).
                           Tunable without code changes.

Revision ID: 0074_lesson_player
Revises: 0073_anomaly_dismissal
Create Date: 2026-05-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0074_lesson_player"
down_revision = "0073_anomaly_dismissal"
branch_labels = None
depends_on = None


_ASSET_KIND_CHECK = sa.text(
    "kind IN ('learning_notebook','practice_notebook','video',"
    "'capstone_brief','reading')"
)
_PROGRESS_STATUS_CHECK = sa.text(
    "status IN ('not_started','in_progress','completed')"
)


def upgrade() -> None:
    # ---- lessons.completion_policy ------------------------------------
    # JSON (not JSONB) per the lessons-learned: keeps SQLite test DBs
    # happy. We never query inside the policy server-side so JSONB
    # operators aren't needed.
    op.add_column(
        "lessons",
        sa.Column("completion_policy", sa.JSON(), nullable=True),
    )

    # ---- lesson_assets ------------------------------------------------
    op.create_table(
        "lesson_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Opaque storage reference. For kind='video' this is the Mux
        # playback_id; for kind in {learning_notebook, practice_notebook}
        # it is the R2 object key (e.g. "courses/<slug>/<lesson>/01.ipynb").
        # For capstone_brief / reading it may be an R2 markdown key.
        sa.Column("storage_ref", sa.String(length=500), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_ASSET_KIND_CHECK, name="ck_lesson_assets_kind"),
    )
    op.create_index(
        "ix_lesson_assets_lesson_id_order",
        "lesson_assets",
        ["lesson_id", "order"],
    )

    # ---- lesson_prerequisites -----------------------------------------
    # Composite PK prevents duplicate edges. ON DELETE CASCADE on both
    # sides so removing a lesson cleans up its edges in both directions.
    op.create_table(
        "lesson_prerequisites",
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requires_lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("lesson_id", "requires_lesson_id"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requires_lesson_id"], ["lessons.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "lesson_id <> requires_lesson_id",
            name="ck_lesson_prerequisites_no_self_loop",
        ),
    )
    op.create_index(
        "ix_lesson_prerequisites_requires_lesson_id",
        "lesson_prerequisites",
        ["requires_lesson_id"],
    )

    # ---- student_asset_progress ---------------------------------------
    # Per-(student, asset) granular progress. The lesson-level
    # StudentProgress row is the rollup, recomputed by
    # LessonProgressService whenever an asset row updates.
    op.create_table(
        "student_asset_progress",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="not_started"),
        # 0.0 .. 1.0. Mux webhook updates this on watched-time events.
        sa.Column("watch_pct", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_position_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("watched_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # First time this student executed the notebook (notebook assets only).
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["lesson_assets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "student_id", "asset_id", name="uq_student_asset_progress_student_asset"
        ),
        sa.CheckConstraint(_PROGRESS_STATUS_CHECK, name="ck_student_asset_progress_status"),
        sa.CheckConstraint(
            "watch_pct >= 0 AND watch_pct <= 1",
            name="ck_student_asset_progress_watch_pct_range",
        ),
    )
    op.create_index(
        "ix_student_asset_progress_student_id",
        "student_asset_progress",
        ["student_id"],
    )

    # ---- mux_webhook_events -------------------------------------------
    # Append-only ledger keyed UNIQUE on event_id for dedup. Mirrors the
    # PaymentWebhookEvent pattern so we get exactly-once webhook handling
    # under Mux's at-least-once delivery guarantee.
    op.create_table(
        "mux_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("playback_id", sa.String(length=255), nullable=True),
        sa.Column("asset_ref", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", name="uq_mux_webhook_events_event_id"),
    )
    op.create_index(
        "ix_mux_webhook_events_playback_id",
        "mux_webhook_events",
        ["playback_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mux_webhook_events_playback_id", table_name="mux_webhook_events"
    )
    op.drop_table("mux_webhook_events")
    op.drop_index(
        "ix_student_asset_progress_student_id",
        table_name="student_asset_progress",
    )
    op.drop_table("student_asset_progress")
    op.drop_index(
        "ix_lesson_prerequisites_requires_lesson_id",
        table_name="lesson_prerequisites",
    )
    op.drop_table("lesson_prerequisites")
    op.drop_index(
        "ix_lesson_assets_lesson_id_order", table_name="lesson_assets"
    )
    op.drop_table("lesson_assets")
    op.drop_column("lessons", "completion_policy")
