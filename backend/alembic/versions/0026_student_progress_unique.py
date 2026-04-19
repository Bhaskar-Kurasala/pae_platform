"""student_progress unique(student_id, lesson_id) (E2E-DISC-28)

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-19 12:00:00.000000

Background:
  Under concurrent POSTs to `/students/me/lessons/{id}/complete`, the
  get-or-create flow in ProgressService raced and left duplicate rows
  in `student_progress`. Count-based aggregations over-reported.

This migration:
  1. Deduplicates existing rows keeping the oldest id per pair.
  2. Adds a unique constraint on (student_id, lesson_id).

Paired with the app switching to `INSERT ... ON CONFLICT DO UPDATE`
so subsequent completes are idempotent under concurrency.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM student_progress a
        USING student_progress b
        WHERE a.student_id = b.student_id
          AND a.lesson_id = b.lesson_id
          AND a.created_at > b.created_at
        """
    )
    with op.get_context().autocommit_block():
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_student_progress_student_lesson'
                ) THEN
                    ALTER TABLE student_progress
                    ADD CONSTRAINT uq_student_progress_student_lesson
                    UNIQUE (student_id, lesson_id);
                END IF;
            END$$;
            """
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_student_progress_student_lesson", "student_progress", type_="unique"
    )
