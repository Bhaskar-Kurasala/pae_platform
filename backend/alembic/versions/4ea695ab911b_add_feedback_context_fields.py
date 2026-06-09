"""add feedback context fields

Revision ID: 4ea695ab911b
Revises: 0069_users_auth_extensions
Create Date: 2026-05-14 08:14:52.600752

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ea695ab911b'
down_revision: Union[str, Sequence[str], None] = '0069_users_auth_extensions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('feedback', sa.Column('url', sa.String(length=2048), nullable=True))
    op.add_column('feedback', sa.Column('user_agent', sa.String(length=512), nullable=True))
    op.add_column('feedback', sa.Column('viewport_width', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('viewport_height', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('app_version', sa.String(length=64), nullable=True))
    op.add_column(
        'feedback',
        sa.Column('category', sa.String(length=32), nullable=True, server_default='other'),
    )
    op.add_column('feedback', sa.Column('severity', sa.String(length=16), nullable=True))
    op.add_column('feedback', sa.Column('error_id', sa.String(length=64), nullable=True))
    op.add_column('feedback', sa.Column('recent_route_history', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('feedback', 'recent_route_history')
    op.drop_column('feedback', 'error_id')
    op.drop_column('feedback', 'severity')
    op.drop_column('feedback', 'category')
    op.drop_column('feedback', 'app_version')
    op.drop_column('feedback', 'viewport_height')
    op.drop_column('feedback', 'viewport_width')
    op.drop_column('feedback', 'user_agent')
    op.drop_column('feedback', 'url')
