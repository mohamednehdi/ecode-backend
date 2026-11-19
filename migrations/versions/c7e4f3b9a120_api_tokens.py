"""Web service: api_token (keys, quotas, allowed IPs/types) and api_usage (request log)

Revision ID: c7e4f3b9a120
Revises: b5d1e8a2c907
Create Date: 2026-11-19 14:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e4f3b9a120'
down_revision = 'b5d1e8a2c907'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'api_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('token_prefix', sa.String(length=16), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('allowed_ips', sa.Text(), nullable=True),
        sa.Column('allowed_types', sa.Text(), nullable=True),
        sa.Column('quota_hourly', sa.Integer(), nullable=True),
        sa.Column('quota_monthly', sa.Integer(), nullable=True),
        sa.Column('valid_from', sa.DateTime(), nullable=True),
        sa.Column('valid_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_token_token_hash', 'api_token', ['token_hash'], unique=True)

    op.create_table(
        'api_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(['token_id'], ['api_token.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_usage_token_time', 'api_usage', ['token_id', 'created_at'])


def downgrade():
    op.drop_index('ix_api_usage_token_time', table_name='api_usage')
    op.drop_table('api_usage')
    op.drop_index('ix_api_token_token_hash', table_name='api_token')
    op.drop_table('api_token')
