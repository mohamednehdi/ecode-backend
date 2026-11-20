"""api_usage: outcome of each request (status, duration, codes, pages, file type and size) for the statistics

Revision ID: d4b7a1e90c53
Revises: c7e4f3b9a120
Create Date: 2026-11-20 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4b7a1e90c53'
down_revision = 'c7e4f3b9a120'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('api_usage', sa.Column('status_code', sa.SmallInteger(), nullable=True))
    op.add_column('api_usage', sa.Column('duration_ms', sa.Integer(), nullable=True))
    op.add_column('api_usage', sa.Column('codes_found', sa.Integer(), nullable=True))
    op.add_column('api_usage', sa.Column('pages', sa.SmallInteger(), nullable=True))
    op.add_column('api_usage', sa.Column('file_type', sa.String(length=8), nullable=True))
    op.add_column('api_usage', sa.Column('file_bytes', sa.Integer(), nullable=True))
    op.add_column('api_usage', sa.Column('thorough', sa.Boolean(), nullable=True))
    op.create_index('ix_api_usage_created', 'api_usage', ['created_at'])


def downgrade():
    op.drop_index('ix_api_usage_created', table_name='api_usage')
    for column in ('thorough', 'file_bytes', 'file_type', 'pages', 'codes_found', 'duration_ms', 'status_code'):
        op.drop_column('api_usage', column)
