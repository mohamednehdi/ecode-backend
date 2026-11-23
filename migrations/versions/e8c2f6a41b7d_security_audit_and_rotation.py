"""Security: audit log table, and the columns of key rotation (previous key with a grace period)

Revision ID: e8c2f6a41b7d
Revises: d4b7a1e90c53
Create Date: 2026-11-23 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8c2f6a41b7d'
down_revision = 'd4b7a1e90c53'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_email', sa.String(length=120), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('target_type', sa.String(length=20), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('target_name', sa.String(length=100), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_created', 'audit_log', ['created_at'])
    op.create_index('ix_audit_log_action', 'audit_log', ['action', 'created_at'])

    op.add_column('api_token', sa.Column('previous_token_hash', sa.String(length=64), nullable=True))
    op.add_column('api_token', sa.Column('previous_valid_until', sa.DateTime(), nullable=True))
    op.add_column('api_token', sa.Column('rotated_at', sa.DateTime(), nullable=True))
    op.create_index('ix_api_token_previous_token_hash', 'api_token', ['previous_token_hash'])


def downgrade():
    op.drop_index('ix_api_token_previous_token_hash', table_name='api_token')
    for column in ('rotated_at', 'previous_valid_until', 'previous_token_hash'):
        op.drop_column('api_token', column)
    op.drop_index('ix_audit_log_action', table_name='audit_log')
    op.drop_index('ix_audit_log_created', table_name='audit_log')
    op.drop_table('audit_log')
