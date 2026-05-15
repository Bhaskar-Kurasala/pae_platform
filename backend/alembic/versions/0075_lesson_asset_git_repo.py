"""Allow 'git_repo' as a lesson_assets.kind value.

Widens the check constraint added in 0074 to admit a sixth asset kind:
``git_repo``. The player renders these as "Open in GitHub" / "Open in
Colab" links — we don't proxy repo content; admin pastes a URL.

Revision ID: 0075_lesson_asset_git_repo
Revises: 0074_lesson_player
Create Date: 2026-05-15
"""

from alembic import op

revision = "0075_lesson_asset_git_repo"
down_revision = "0074_lesson_player"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_lesson_assets_kind", "lesson_assets", type_="check"
    )
    op.create_check_constraint(
        "ck_lesson_assets_kind",
        "lesson_assets",
        "kind IN ('learning_notebook','practice_notebook','video',"
        "'capstone_brief','reading','git_repo')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_lesson_assets_kind", "lesson_assets", type_="check"
    )
    op.create_check_constraint(
        "ck_lesson_assets_kind",
        "lesson_assets",
        "kind IN ('learning_notebook','practice_notebook','video',"
        "'capstone_brief','reading')",
    )
