"""add agent task template table

Revision ID: 0072_agent_task_template
Revises: 77d8139a3660
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0072_agent_task_template"
down_revision: Union[str, Sequence[str], None] = "77d8139a3660"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Built-in template seeds: (agent_name, label, body, sort_order)
_SEEDS: list[tuple[str, str, str, int]] = [
    # disrupt_prevention
    (
        "disrupt_prevention",
        "Gentle re-engagement nudge",
        "Write a short, warm message acknowledging the student hasn't been around for a few days. Mention one small thing they could do today to get unstuck. Avoid guilt. End with a single concrete question.",
        10,
    ),
    (
        "disrupt_prevention",
        "Suggest a quick win",
        "Suggest one small task this student can ship today based on their recent activity. The task should take under 30 minutes and reconnect them to their goal.",
        20,
    ),
    (
        "disrupt_prevention",
        "Weekend check-in",
        "Draft a casual Friday afternoon check-in. Ask how the week went, mention one thing you noticed they did well, and offer help for next week.",
        30,
    ),
    # progress_report
    (
        "progress_report",
        "Encouraging 3-bullet weekly summary",
        "Write a 3-bullet weekly progress summary in an encouraging tone. Lead with what they accomplished, then one gentle area to work on, then a clear next action for next week.",
        10,
    ),
    (
        "progress_report",
        "Last-2-weeks capstone focus",
        "Focus this progress report on the student's capstone work over the last 2 weeks. Specifically call out what shipped vs. what stalled, and suggest the single highest-leverage thing to do next.",
        20,
    ),
    (
        "progress_report",
        "Cohort comparison",
        "Generate a progress report that compares this student's pace to the cohort median. Frame it constructively — if behind, suggest a catch-up plan; if ahead, suggest a stretch goal.",
        30,
    ),
    # mock_interview
    (
        "mock_interview",
        "5-question system design round",
        "Run a 5-question system design interview round. Start broad (design a URL shortener / chat app) and drill into one trade-off per question. Stay in interviewer voice.",
        10,
    ),
    (
        "mock_interview",
        "Behavioral round: teamwork",
        "Conduct a behavioral interview round focused on teamwork. Ask 4 STAR-format questions about conflict, collaboration, and ownership.",
        20,
    ),
    (
        "mock_interview",
        "Coding round: algorithms",
        "Conduct a 30-minute coding interview round focused on algorithm fundamentals. Start with one easy warm-up, then one medium. Probe for time/space complexity reasoning.",
        30,
    ),
    (
        "mock_interview",
        "ML systems round",
        "Conduct a 30-minute ML systems interview round. Cover data pipelines, model training, monitoring drift, and online vs. batch trade-offs.",
        40,
    ),
    # socratic_tutor
    (
        "socratic_tutor",
        "Re-explain with a different metaphor",
        "The student got a concept wrong. Re-explain it using a different metaphor or analogy than they would have seen in the lesson. Don't give the answer directly — guide them to it with 2-3 leading questions.",
        10,
    ),
    (
        "socratic_tutor",
        "Diagnose the misconception",
        "Identify the specific misconception behind the student's recent confusion. Ask one targeted question that surfaces the gap, then offer a tiny worked example.",
        20,
    ),
    (
        "socratic_tutor",
        "Bridge from familiar to new",
        "Connect the new concept the student is struggling with to something they already understand from earlier in the course. Use the bridge as the basis for a Socratic exchange.",
        30,
    ),
    # cover_letter
    (
        "cover_letter",
        "Series A startup, backend AI",
        "Tailor the cover letter to a backend-heavy AI engineer role at a Series A startup. Emphasize production reliability, ownership, and shipping fast. Keep it under 250 words.",
        10,
    ),
    (
        "cover_letter",
        "Big-tech IC4 ML role",
        "Tailor the cover letter to an IC4-level ML engineer role at a FAANG-tier company. Emphasize systems thinking, scale, and rigorous evaluation. Lean professional.",
        20,
    ),
]


def upgrade() -> None:
    op.create_table(
        "agent_task_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_built_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_agent_task_template_agent_name", "agent_task_template", ["agent_name"]
    )

    # Seed built-in templates. Try pgcrypto's gen_random_uuid() first.
    bind = op.get_bind()
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        uuid_expr = "gen_random_uuid()"
    except Exception:
        uuid_expr = "gen_random_uuid()"  # pgvector image ships pgcrypto; assume available

    for agent_name, label, body, sort_order in _SEEDS:
        bind.execute(
            sa.text(
                f"""
                INSERT INTO agent_task_template
                    (id, agent_name, label, body, created_by_admin_id, is_built_in, sort_order)
                VALUES
                    ({uuid_expr}, :agent_name, :label, :body, NULL, true, :sort_order)
                """
            ),
            {
                "agent_name": agent_name,
                "label": label,
                "body": body,
                "sort_order": sort_order,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_agent_task_template_agent_name", table_name="agent_task_template")
    op.drop_table("agent_task_template")
